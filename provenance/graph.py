"""Versioned evidence DAG. Temporal and possible edges are never causal proof."""
import networkx as nx


def build(events, policy, run, *, include_task=True):
    g = nx.MultiDiGraph(run_id=run.name)
    def node(key, typ, **attrs):
        g.add_node(key, node_type=typ, **attrs)
    def edge(a,b,rel,status='observed',ref=''):
        g.add_edge(a,b,relation=rel,evidence_status=status,source_ref=ref)
    if include_task:
        node('task','TrustedTask',source_ref='prompt.txt',label='Task policy (prepared; delivery unknown)')
    previous = None
    calls, turns, results = {}, {}, []
    for e in events:
        typ = {'model_turn':'ModelTurn','model_request':'ModelRequest','initial_prompt':'InitialPrompt','tool_call':'ToolCall','tool_result':'ToolResult','final_response':'FinalResponse'}.get(e.kind,'Observation')
        node(e.event_id,typ,source_ref=e.source_ref,label=f'{e.event_id} {e.tool_name or e.kind}',order=e.order)
        if previous: edge(previous,e.event_id,'PRECEDED','chronological',e.source_ref)
        previous = e.event_id
        if e.kind == 'model_turn' and e.turn_id: turns[e.turn_id]=e.event_id
        if e.kind == 'model_request':
            # Exact text containment is evidence of recorded context availability.
            for result in results:
                if result.text and result.text in e.text:
                    edge(result.event_id,e.event_id,'AVAILABLE_TO_MODEL','observed',e.source_ref)
            for line in (run/'prompt.txt').read_text().splitlines() if include_task and (run/'prompt.txt').exists() else []:
                if line.strip() and line in e.text:
                    edge('task',e.event_id,'TASK_TEXT_PRESENT','observed',e.source_ref); break
        if e.kind == 'tool_call':
            if e.turn_id in turns: edge(turns[e.turn_id],e.event_id,'INVOKED',ref=e.source_ref)
            if e.call_id: calls[e.call_id]=e.event_id
            for result in results:
                # Sibling calls emitted in one model message cannot consume each
                # other's results. Export part order alone does not create context.
                if e.turn_id and e.turn_id==result.turn_id:
                    continue
                edge(result.event_id,e.event_id,'POSSIBLY_AVAILABLE','uncertain',e.source_ref)
            if e.path and e.tool_name.lower() in ('read','read_file'):
                key=f'file-observed:{e.event_id}'
                node(key,'FileVersion',path=e.path,label=e.path+' (read target; hash unknown)',source_ref=e.source_ref)
                completed=any(r.kind=='tool_result' and r.call_id==e.call_id and r.order>e.order and r.status not in ('error','failed') for r in events) if e.call_id else False
                edge(key,e.event_id,'READ_FROM' if completed else 'READ_TARGET','observed' if completed else 'intent_only',e.source_ref)
        if e.kind == 'tool_result':
            if e.call_id in calls: edge(calls[e.call_id],e.event_id,'RETURNED',ref=e.source_ref)
            results.append(e)
    for i,c in enumerate(policy['changes']):
        before,change,after = f'file:{i}:before',f'integrity:{i}',f'file:{i}:after'
        for key,ver in ((before,'before'),(after,'after')):
            node(key,'FileVersion',path=c['path'],version=ver,sha256=c[ver] or 'absent',label=c['path']+' '+ver,source_ref='baseline.json' if ver=='before' else 'workspace snapshot')
        node(change,'IntegrityChange',label='Run-level integrity change',source_ref='baseline.json + workspace snapshot')
        edge(before,change,'COMPARED_WITH',ref='baseline.json')
        edge(change,after,'WROTE_TO','observed_run_level','workspace snapshot')
    for i,path in enumerate(policy['protected_paths_changed']):
        finding=f'finding:{i}'
        node(finding,'PolicyFinding',label='Protected change: '+path,path=path,source_ref='check.json + snapshot' if policy['checker_present'] else 'snapshot')
        for key,attrs in list(g.nodes(data=True)):
            if attrs['node_type']=='FileVersion' and attrs.get('version')=='after' and attrs['path']==path:
                edge(key,finding,'EVIDENCE_FOR',ref=attrs['source_ref'])
        for a in policy['attempts']:
            if a['path']==path:
                edge(a['event_id'],finding,'INFLUENCE_HYPOTHESIS','hypothesis',a['source_ref'])
    if not nx.is_directed_acyclic_graph(g):
        raise ValueError('Evidence graph has a cycle; refusing export')
    return g
