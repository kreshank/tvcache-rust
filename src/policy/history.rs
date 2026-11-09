//! Causal request history, separate from residency. Eviction never erases history.
use super::*;
use std::collections::{BTreeMap, BTreeSet, HashMap};

#[derive(Default)]
struct Observation {
    id: Option<EntryId>,
    accesses: u64,
    last: Option<AccessContext>,
    subtree_accesses: u64,
    subtree_last: Option<AccessContext>,
    children: BTreeSet<String>,
}

#[derive(Default)]
pub(crate) struct ObservedHistory(HashMap<String, HashMap<Vec<String>, Observation>>);

impl ObservedHistory {
    pub fn features(&self, entry: &EntryMeta, now: AccessContext) -> AccessFeatures {
        let task = self.0.get(&entry.id.task_id);
        let current = task.and_then(|t| t.get(entry.path.as_slice()));
        let parent = task.and_then(|t| t.get(&entry.path[..entry.path.len() - 1]));
        let last = current.and_then(|o| o.last);
        AccessFeatures {
            access_count_before: current.map_or(0, |o| o.accesses),
            last_access_index: last.map(|a| a.event_index),
            events_since_last_access: last.map(|a| now.event_index.saturating_sub(a.event_index)),
            time_since_last_access_ms: last.map(|a| (now.time_ms - a.time_ms).max(0.0)),
            events_since_subtree_access: current
                .and_then(|o| o.subtree_last)
                .map(|a| now.event_index.saturating_sub(a.event_index)),
            observed_children_before: current.map_or(0, |o| o.children.len() as u64),
            observed_parent_children_before: parent.map_or(0, |o| o.children.len() as u64),
            stateful_prefix_depth: entry.path.len().saturating_sub(1) as u64,
            subtree_access_count_before: current.map_or(0, |o| o.subtree_accesses),
            extra: BTreeMap::new(),
        }
    }

    pub fn observe(&mut self, entry: &EntryMeta, now: AccessContext) {
        let task = self.0.entry(entry.id.task_id.clone()).or_default();
        for depth in 0..=entry.path.len() {
            let prefix = &entry.path[..depth];
            if !task.contains_key(prefix) {
                task.insert(prefix.to_vec(), Observation::default());
            }
            let o = task.get_mut(prefix).unwrap();
            o.subtree_accesses += 1;
            o.subtree_last = Some(now);
            if depth == entry.path.len() {
                if o.id.is_none() {
                    o.id = Some(entry.id.clone());
                }
                o.accesses += 1;
                o.last = Some(now);
            } else {
                if !o.children.contains(&entry.path[depth]) {
                    o.children.insert(entry.path[depth].clone());
                }
            }
        }
    }

    /// Only IDs already observed on this task's prefix; no future catalog access.
    pub fn ancestors(&self, entry: &EntryMeta) -> Vec<EntryId> {
        let task = self.0.get(&entry.id.task_id).unwrap();
        (1..=entry.path.len())
            .filter_map(|depth| task.get(&entry.path[..depth]).and_then(|o| o.id.clone()))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(task: &str, path: &[&str]) -> EntryMeta {
        EntryMeta {
            id: EntryId {
                task_id: task.into(),
                node_id: path.join("/"),
            },
            parent: None,
            path: path.iter().map(|s| (*s).into()).collect(),
            depth: path.len() as u64,
            mutates_state: true,
            tool: "test".into(),
            cache_entry_bytes: 64,
            value_bytes: 64,
            runtime_ms: None,
            tool_cost_usd: None,
            snapshot: None,
        }
    }

    #[test]
    fn features_age_and_ancestors_update_without_future_information() {
        let mut history = ObservedHistory::default();
        let root = entry("t", &["a"]);
        let child = entry("t", &["a", "b"]);
        let at = |i| AccessContext {
            event_index: i,
            time_ms: i as f64,
        };
        let before = history.features(&root, at(0));
        assert_eq!(before.access_count_before, 0);
        assert_eq!(before.observed_children_before, 0);
        assert_eq!(before.events_since_last_access, None);
        history.observe(&root, at(0));
        history.observe(&child, at(3));
        assert_eq!(
            history.ancestors(&child),
            vec![root.id.clone(), child.id.clone()]
        );
        let after = history.features(&root, at(10));
        assert_eq!(after.access_count_before, 1);
        assert_eq!(after.subtree_access_count_before, 2);
        assert_eq!(after.events_since_last_access, Some(10));
        assert_eq!(after.events_since_subtree_access, Some(7));
        assert_eq!(after.observed_children_before, 1);
        let other_task = entry("other", &["a"]);
        assert_eq!(history.features(&other_task, at(10)).access_count_before, 0);
        // Merely inspecting an unseen branch never changes observed structure.
        history.features(&entry("t", &["a", "future"]), at(11));
        assert_eq!(
            history.ancestors(&entry("t", &["a", "future"])),
            vec![root.id.clone()]
        );
        assert_eq!(history.features(&root, at(11)).observed_children_before, 1);
    }
}
