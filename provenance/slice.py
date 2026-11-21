"""Backward evidence queries, excluding chronology from dependency traversal."""
import networkx as nx

OBSERVED = {'INVOKED','RETURNED','READ_FROM','AVAILABLE_TO_MODEL','TASK_TEXT_PRESENT','COMPARED_WITH','WROTE_TO','EVIDENCE_FOR',
            'PROMPT_FOR','RECORDED_HANDOFF','HANDOFF_IN_PROMPT','MATCHES_ARTIFACT','USED_BY_CHECK','MATCHES_FINAL'}


def backward_slice(graph, target):
    if target not in graph: raise ValueError(f'Unknown graph node: {target}')
    def ancestors(relations):
        g=nx.DiGraph()
        g.add_nodes_from(graph)
        g.add_edges_from((a,b) for a,b,d in graph.edges(data=True) if d['relation'] in relations)
        return nx.ancestors(g,target)|{target}
    observed=ancestors(OBSERVED)
    possible=ancestors(OBSERVED|{'POSSIBLY_AVAILABLE','INFLUENCE_HYPOTHESIS'})-observed
    def refs(keys):
        return [dict(node=k,**graph.nodes[k]) for k in sorted(keys)]
    return dict(target=target,observed=refs(observed),possible=refs(possible),
                attribution=graph.graph.get('attribution','Run-level final changes do not identify the responsible tool. Possible contexts and matching edit attempts are hypotheses.'),
                candidate_tool_results=sum(graph.nodes[k]['node_type']=='ToolResult' for k in possible|observed))
