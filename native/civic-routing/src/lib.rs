//! A small domain-only router. Geometry and resident ownership stay in the caller.
//!
//! Nodes must be numbered in the caller's lexicographic ID order. Outgoing arcs
//! must retain the Python router's sorted order. Equal-cost discoveries retain
//! the first predecessor; the min-heap breaks equal distances by node number.

#![deny(unsafe_op_in_unsafe_fn)]

use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;
use std::slice;

const MAX_NODES: usize = 2_000_000;
const MAX_ARCS: usize = 8_000_000;

pub struct Graph {
    offsets: Vec<u32>,
    targets: Vec<u32>,
    lengths: Vec<f64>,
}

#[derive(Clone, Copy, Debug)]
struct Visit {
    cost: f64,
    node: u32,
}

impl PartialEq for Visit {
    fn eq(&self, other: &Self) -> bool {
        self.cost == other.cost && self.node == other.node
    }
}
impl Eq for Visit {}
impl PartialOrd for Visit {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for Visit {
    fn cmp(&self, other: &Self) -> Ordering {
        // BinaryHeap is a max-heap; invert both Python tuple priority fields.
        other
            .cost
            .total_cmp(&self.cost)
            .then_with(|| other.node.cmp(&self.node))
    }
}

impl Graph {
    fn new(offsets: Vec<u32>, targets: Vec<u32>, lengths: Vec<f64>) -> Option<Self> {
        let nodes = offsets.len().checked_sub(1)?;
        if nodes == 0
            || nodes > MAX_NODES
            || targets.len() > MAX_ARCS
            || targets.len() != lengths.len()
            || offsets.first() != Some(&0)
            || offsets.last().copied()? as usize != targets.len()
            || offsets.windows(2).any(|pair| pair[0] > pair[1])
            || targets.iter().any(|&target| target as usize >= nodes)
            || lengths
                .iter()
                .any(|&length| !length.is_finite() || length <= 0.0)
        {
            return None;
        }
        Some(Self {
            offsets,
            targets,
            lengths,
        })
    }

    fn route(&self, origin: u32, destination: u32) -> Result<Option<(Vec<u32>, f64)>, ()> {
        let nodes = self.offsets.len() - 1;
        if origin as usize >= nodes || destination as usize >= nodes {
            return Err(());
        }
        let mut costs = vec![f64::INFINITY; nodes];
        let mut previous = vec![None; nodes];
        let mut queue = BinaryHeap::new();
        costs[origin as usize] = 0.0;
        queue.push(Visit {
            cost: 0.0,
            node: origin,
        });
        while let Some(Visit { cost, node }) = queue.pop() {
            if cost != costs[node as usize] {
                continue;
            }
            if node == destination {
                let mut steps = Vec::new();
                let mut current = destination;
                while current != origin {
                    let (parent, arc) = previous[current as usize].ok_or(())?;
                    steps.push(arc);
                    current = parent;
                }
                steps.reverse();
                return Ok(Some((steps, cost)));
            }
            let range = self.offsets[node as usize]..self.offsets[node as usize + 1];
            for arc in range {
                let target = self.targets[arc as usize];
                let candidate = cost + self.lengths[arc as usize];
                if candidate < costs[target as usize] {
                    costs[target as usize] = candidate;
                    previous[target as usize] = Some((node, arc));
                    queue.push(Visit {
                        cost: candidate,
                        node: target,
                    });
                }
            }
        }
        Ok(None)
    }
}

#[no_mangle]
pub extern "C" fn civic_routing_abi_version() -> u32 {
    1
}

/// Copy a trusted caller's CSR graph. Null means malformed input or a caught panic.
///
/// # Safety
/// All pointers must refer to readable arrays of the declared lengths for this
/// call. A non-null result is uniquely owned and must be freed exactly once.
#[no_mangle]
pub unsafe extern "C" fn civic_graph_new(
    node_count: u32,
    arc_count: u32,
    offsets: *const u32,
    targets: *const u32,
    lengths: *const f64,
) -> *mut Graph {
    if node_count == 0
        || node_count as usize > MAX_NODES
        || arc_count as usize > MAX_ARCS
        || offsets.is_null()
        || targets.is_null()
        || lengths.is_null()
    {
        return ptr::null_mut();
    }
    catch_unwind(AssertUnwindSafe(|| {
        let offsets = unsafe { slice::from_raw_parts(offsets, node_count as usize + 1) }.to_vec();
        let targets = unsafe { slice::from_raw_parts(targets, arc_count as usize) }.to_vec();
        let lengths = unsafe { slice::from_raw_parts(lengths, arc_count as usize) }.to_vec();
        Graph::new(offsets, targets, lengths)
            .map(|graph| Box::into_raw(Box::new(graph)))
            .unwrap_or(ptr::null_mut())
    }))
    .unwrap_or(ptr::null_mut())
}

/// Release a graph created by civic_graph_new. Null is accepted.
///
/// # Safety
/// A non-null pointer must be a live, uniquely owned result of civic_graph_new.
/// No route calls may be active while the graph is freed.
#[no_mangle]
pub unsafe extern "C" fn civic_graph_free(graph: *mut Graph) {
    if !graph.is_null() {
        drop(unsafe { Box::from_raw(graph) });
    }
}

/// Return arc indices: 0=route, 1=unreachable, 2=buffer too small, -1=invalid.
/// Output length is the required capacity on code 2. No partial route is written.
///
/// # Safety
/// graph must be a live result of civic_graph_new. Output buffers must be writable
/// for their declared lengths, aligned, and not alias this graph's data. The graph
/// is immutable and may be routed concurrently while its owner keeps it alive.
#[no_mangle]
pub unsafe extern "C" fn civic_graph_route(
    graph: *const Graph,
    origin: u32,
    destination: u32,
    output: *mut u32,
    capacity: u32,
    output_length: *mut u32,
    output_cost: *mut f64,
) -> i32 {
    if graph.is_null() || output.is_null() || output_length.is_null() || output_cost.is_null() {
        return -1;
    }
    unsafe {
        *output_length = 0;
        *output_cost = f64::INFINITY;
    }
    catch_unwind(AssertUnwindSafe(|| {
        let graph = unsafe { &*graph };
        match graph.route(origin, destination) {
            Ok(Some((steps, cost))) => {
                unsafe {
                    *output_length = steps.len() as u32;
                    *output_cost = cost;
                }
                if steps.len() > capacity as usize {
                    return 2;
                }
                unsafe {
                    ptr::copy_nonoverlapping(steps.as_ptr(), output, steps.len());
                }
                0
            }
            Ok(None) => 1,
            Err(()) => -1,
        }
    }))
    .unwrap_or(-1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn equal_cost_routes_match_lexicographic_heap_and_keep_first_parallel_arc() {
        // a -> b/c -> d; duplicate a->b follows the first a->b arc.
        let graph = Graph::new(vec![0, 3, 4, 5, 5], vec![1, 1, 2, 3, 3], vec![1.0; 5]).unwrap();
        assert_eq!(graph.route(0, 3), Ok(Some((vec![0, 3], 2.0))));
        assert_eq!(graph.route(3, 0), Ok(None));
        assert_eq!(graph.route(2, 2), Ok(Some((vec![], 0.0))));
    }

    #[test]
    fn cheaper_later_discovery_replaces_predecessor_and_stale_queue_entry() {
        let graph = Graph::new(
            vec![0, 2, 3, 5, 5],
            vec![1, 2, 3, 1, 3],
            vec![9.0, 1.0, 1.0, 1.0, 9.0],
        )
        .unwrap();
        assert_eq!(graph.route(0, 3), Ok(Some((vec![1, 3, 2], 3.0))));
        assert_eq!(graph.route(4, 0), Err(()));
    }

    #[test]
    fn rejects_nonfinite_nonpositive_and_malformed_graphs() {
        for length in [0.0, -1.0, f64::INFINITY, f64::NAN] {
            assert!(Graph::new(vec![0, 1, 1], vec![1], vec![length]).is_none());
        }
        assert!(Graph::new(vec![0, 1, 0], vec![], vec![]).is_none());
        assert!(Graph::new(vec![0, 1], vec![1], vec![1.0]).is_none());
    }

    #[test]
    fn ffi_checks_capacity_before_writing_and_can_be_freed() {
        let graph =
            unsafe { civic_graph_new(2, 1, [0, 1, 1].as_ptr(), [1].as_ptr(), [1.0].as_ptr()) };
        assert!(!graph.is_null());
        let mut output = [99];
        let (mut length, mut cost) = (0, 0.0);
        let status = unsafe {
            civic_graph_route(graph, 0, 1, output.as_mut_ptr(), 0, &mut length, &mut cost)
        };
        assert_eq!(status, 2);
        assert_eq!(output, [99]);
        assert_eq!(length, 1);
        let status = unsafe {
            civic_graph_route(graph, 0, 1, output.as_mut_ptr(), 1, &mut length, &mut cost)
        };
        assert_eq!(status, 0);
        assert_eq!(output, [0]);
        unsafe {
            civic_graph_free(graph);
            civic_graph_free(ptr::null_mut());
        }
    }
}
