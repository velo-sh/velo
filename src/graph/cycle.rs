/// Tarjan's SCC algorithm for cycle detection
pub struct Tarjan {
    index: usize,
    stack: Vec<usize>,
    on_stack: Vec<bool>,
    indices: Vec<Option<usize>>,
    lowlink: Vec<usize>,
    sccs: Vec<Vec<usize>>,
}

impl Tarjan {
    pub fn new(node_count: usize) -> Self {
        Self {
            index: 0,
            stack: Vec::new(),
            on_stack: vec![false; node_count],
            indices: vec![None; node_count],
            lowlink: vec![0; node_count],
            sccs: Vec::new(),
        }
    }

    pub fn execute(mut self, edges: &[Vec<usize>]) -> Vec<Vec<usize>> {
        for i in 0..edges.len() {
            if self.indices[i].is_none() {
                self.strongconnect(i, edges);
            }
        }
        self.sccs
    }

    fn strongconnect(&mut self, v: usize, edges: &[Vec<usize>]) {
        self.indices[v] = Some(self.index);
        self.lowlink[v] = self.index;
        self.index += 1;
        self.stack.push(v);
        self.on_stack[v] = true;

        for &w in &edges[v] {
            if self.indices[w].is_none() {
                self.strongconnect(w, edges);
                self.lowlink[v] = self.lowlink[v].min(self.lowlink[w]);
            } else if self.on_stack[w] {
                self.lowlink[v] = self.lowlink[v].min(self.indices[w].unwrap());
            }
        }

        if self.lowlink[v] == self.indices[v].unwrap() {
            let mut scc = Vec::new();
            while let Some(w) = self.stack.pop() {
                self.on_stack[w] = false;
                scc.push(w);
                if w == v {
                    break;
                }
            }
            if scc.len() > 1 {
                self.sccs.push(scc);
            } else {
                // Check for self-loop
                if edges[v].contains(&v) {
                    self.sccs.push(scc);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_cycle() {
        // 0 -> 1 -> 0
        let edges = vec![vec![1], vec![0]];
        let tarjan = Tarjan::new(2);
        let sccs = tarjan.execute(&edges);
        assert_eq!(sccs.len(), 1);
        assert!(sccs[0].contains(&0));
        assert!(sccs[0].contains(&1));
    }

    #[test]
    fn test_diamond_no_cycle() {
        // 0 -> 1, 0 -> 2, 1 -> 3, 2 -> 3
        let edges = vec![vec![1, 2], vec![3], vec![3], vec![]];
        let tarjan = Tarjan::new(4);
        let sccs = tarjan.execute(&edges);
        assert_eq!(sccs.len(), 0);
    }

    #[test]
    fn test_two_sccs() {
        // 0 -> 1 -> 0, 2 -> 3 -> 2, 1 -> 2
        let edges = vec![vec![1], vec![0, 2], vec![3], vec![2]];
        let tarjan = Tarjan::new(4);
        let sccs = tarjan.execute(&edges);
        assert_eq!(sccs.len(), 2);
    }
}
