"""Offline evidence graph for the CSV experiment's completed run format."""

import hashlib
import json
import re
from pathlib import Path

import networkx as nx

from .graph import build
from .report import export_graph
from .responses_log import read_session
from .slice import backward_slice

EXECUTOR = 'records/executor.jsonl'
VERIFIER = 'records/verifier/events.jsonl'
EVALUATION = 'records/evaluation.json'
VALIDATION = 'records/validation.json'
HANDOFF = 'records/handoff.txt'
SCRIPT = 'records/validator.py'
CHILD_SCRIPT = 'records/verifier/validator.py'
CHECKED = 'records/checked-result.json'
CHECKED_INPUT = 'records/checked-input.csv'
FINAL = 'workspace/outputs/summary.json'
TARGET = 'release:decision'
ATTRIBUTION = ('Observed links describe recorded calls, exact text or artifact matches, and saved decisions. '
               'Possible context links do not establish influence.')


def read_object(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path.name} must contain a JSON object')
    return data


def read_artifact(run, filename):
    path = run / filename
    return path.read_bytes() if path.is_file() and not path.is_symlink() else None


def add_node(graph, key, kind, label, ref, **attrs):
    graph.add_node(key, node_type=kind, label=label, source_ref=ref, **attrs)


def link(graph, source, target, relation, ref):
    graph.add_edge(source, target, relation=relation, evidence_status='observed', source_ref=ref)


def add_session(graph, session, run):
    events = session.events
    session_graph = build(events, {'changes': [], 'protected_paths_changed': []}, run,
                          include_task=False)
    graph.update(session_graph)
    first_turn = next((event for event in events if event.kind == 'model_turn'), None)
    if first_turn and events[0].kind == 'initial_prompt':
        link(graph, events[0].event_id, first_turn.event_id, 'PROMPT_FOR', events[0].source_ref)


def add_validator(graph, run, executor, verifier, warnings):
    script = read_artifact(run, SCRIPT)
    if script is None:
        if verifier or any(x.call.tool_name == 'request_validator' for x in executor.exchanges):
            warnings.append(f'{SCRIPT}: saved validator unavailable')
        return None
    digest = hashlib.sha256(script).hexdigest()
    add_node(graph, 'validator:script', 'FileVersion', 'Saved validator script', SCRIPT, sha256=digest)
    delegations = [x for x in executor.exchanges
                   if x.call.tool_name == 'request_validator' and x.output.get('validator_id') == digest]
    delegation = delegations[0] if len(delegations) == 1 else None
    if delegation:
        link(graph, 'validator:script', delegation.result.event_id, 'MATCHES_ARTIFACT',
             delegation.result.source_ref)
    if verifier is None:
        if delegation:
            warnings.append(f'{VERIFIER}: child session unavailable')
        return digest

    handoff = read_artifact(run, HANDOFF)
    forwarded = verifier.prompt.partition('\nHANDOFF:\n')[2].encode('utf-8')
    requested = delegation.arguments.get('handoff') if delegation else None
    if isinstance(requested, str) and handoff and requested.encode('utf-8') == handoff == forwarded:
        add_node(graph, 'validator:handoff', 'Handoff', 'Saved delegation handoff', HANDOFF)
        link(graph, delegation.call.event_id, 'validator:handoff', 'RECORDED_HANDOFF', HANDOFF)
        prompt = verifier.events[0]
        link(graph, 'validator:handoff', prompt.event_id, 'HANDOFF_IN_PROMPT', prompt.source_ref)
    else:
        warnings.append(f'{HANDOFF}: delegation, saved handoff and child prompt could not be matched')

    writes = [x for x in verifier.exchanges
              if x.call.tool_name == 'write_file' and x.call.path == 'validator.py'
              and x.output.get('written') is True]
    last_write = writes[-1] if writes else None
    written = last_write.arguments.get('content') if last_write else None
    if isinstance(written, str) and written.encode('utf-8') == script == read_artifact(run, CHILD_SCRIPT):
        link(graph, last_write.result.event_id, 'validator:script', 'MATCHES_ARTIFACT', CHILD_SCRIPT)
    else:
        warnings.append(f'{SCRIPT}: child write and both saved script copies could not be matched')
    return digest


def add_validation(graph, run, executor, evaluation, script_hash, warnings):
    path = run / VALIDATION
    if not path.is_file():
        if evaluation.get('validation') is not None:
            warnings.append(f'{VALIDATION}: recorded check file unavailable')
        return
    validation = read_object(path)
    status = validation.get('status')
    if status not in ('pass', 'fail', 'unavailable'):
        raise ValueError(f'{VALIDATION}: unsupported validation status')
    label = f'Validation {status.upper()}'
    syntax_line = None
    stderr = validation.get('stderr')
    if status == 'unavailable' and isinstance(stderr, str) and re.search(r'^SyntaxError:', stderr, re.M):
        label += ' (SyntaxError)'
        location = re.search(r'^\s*File "/work/validator\.py", line (\d+)', stderr, re.M)
        if location:
            syntax_line = int(location[1])
    add_node(graph, 'validator:check', 'ValidationOutcome', label, VALIDATION, status=status)
    if validation == evaluation.get('validation') and status == evaluation.get('validation_status'):
        link(graph, 'validator:check', TARGET, 'EVIDENCE_FOR', f'{EVALUATION}:/validation')
    else:
        warnings.append(f'{VALIDATION}: check record differs from saved evaluation')

    checks = [x for x in executor.exchanges if x.call.tool_name == 'run_validator' and x.output == validation]
    if len(checks) != 1:
        warnings.append(f'{VALIDATION}: could not match a unique tool result to the check record')
        return
    check = checks[0]
    link(graph, check.result.event_id, 'validator:check', 'EVIDENCE_FOR', VALIDATION)
    if script_hash is not None and check.arguments.get('validator_id') == script_hash == validation.get('script_sha256'):
        link(graph, 'validator:script', check.call.event_id, 'USED_BY_CHECK', f'{VALIDATION}:/script_sha256')
        if syntax_line is not None:
            graph.nodes['validator:check']['diagnostic_ref'] = f'{SCRIPT}:line-{syntax_line}'
    else:
        warnings.append(f'{SCRIPT}: saved script hash and recorded check identity could not be matched')

    for key, filename, label in (('result:checked', CHECKED, 'Checked result'),
                                 ('input:checked', CHECKED_INPUT, 'Checked CSV input')):
        saved = read_artifact(run, filename)
        if saved is None:
            warnings.append(f'{filename}: checked snapshot unavailable')
            continue
        add_node(graph, key, 'FileVersion', label, filename, sha256=hashlib.sha256(saved).hexdigest())
        link(graph, key, check.call.event_id, 'USED_BY_CHECK', filename)
        if key == 'result:checked':
            add_final_match(graph, run, evaluation, saved, warnings)


def add_final_match(graph, run, evaluation, checked, warnings):
    final = read_artifact(run, FINAL)
    recorded_match = evaluation.get('checked_result_unchanged')
    if final is not None and final == checked and recorded_match is True:
        add_node(graph, 'result:final', 'FileVersion', 'Final summary matches checked result', FINAL,
                 sha256=hashlib.sha256(final).hexdigest())
        link(graph, 'result:checked', 'result:final', 'MATCHES_FINAL', f'{EVALUATION}:/checked_result_unchanged')
        link(graph, 'result:final', TARGET, 'EVIDENCE_FOR', f'{EVALUATION}:/checked_result_unchanged')
    elif recorded_match is True:
        warnings.append(f'{FINAL}: current final summary does not match the saved checked result')


def analyze_responses(run, output):
    run, output = Path(run).resolve(), Path(output).resolve()
    if output.is_relative_to(run):
        raise ValueError('Output directory must be outside the input run')
    if not (run / EXECUTOR).is_file() or not (run / EVALUATION).is_file():
        raise ValueError(f'Expected {EXECUTOR} and {EVALUATION} in the CSV experiment run')
    evaluation = read_object(run / EVALUATION)
    fields = ('oracle_correct', 'released', 'wrong_released')
    if any(type(evaluation.get(field)) is not bool for field in fields):
        raise ValueError(f'{EVALUATION}: expected boolean oracle and release fields')
    if evaluation['wrong_released'] != (evaluation['released'] and not evaluation['oracle_correct']):
        raise ValueError(f'{EVALUATION}: inconsistent oracle and release fields')

    graph = nx.MultiDiGraph(run_id=run.name, attribution=ATTRIBUTION)
    executor = read_session(run, EXECUTOR, 'executor')
    verifier = read_session(run, VERIFIER, 'verifier') if (run / VERIFIER).is_file() else None
    warnings = list(executor.warnings)
    add_session(graph, executor, run)
    if verifier:
        add_session(graph, verifier, run)
        warnings.extend(verifier.warnings)
    outcome = {field: evaluation[field] for field in fields}
    action = 'Released' if outcome['released'] else 'Withheld'
    correctness = 'correct' if outcome['oracle_correct'] else 'incorrect'
    add_node(graph, TARGET, 'ReleaseDecision', f'{action} {correctness} result', f'{EVALUATION}:/released',
             **outcome)
    add_node(graph, 'release:oracle', 'OracleVerdict', f'Independent oracle: {correctness}',
             f'{EVALUATION}:/oracle_correct')
    link(graph, 'release:oracle', TARGET, 'EVIDENCE_FOR', f'{EVALUATION}:/wrong_released')
    digest = add_validator(graph, run, executor, verifier, warnings)
    add_validation(graph, run, executor, evaluation, digest, warnings)

    evidence = backward_slice(graph, TARGET)
    report = dict(run_id=run.name, source='csv_experiment_responses', decision=outcome,
                  validation_status=evaluation.get('validation_status'), warnings=warnings, slices=[evidence])
    export_graph(graph, output, new_output=True)
    (output / 'analysis.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    check_label = 'No validation record matched the saved decision'
    if graph.has_edge('validator:check', TARGET):
        check_label = graph.nodes['validator:check']['label']
    lines = [f'# Responses evidence for run {run.name}', '',
             f'**{action} {correctness} result.** {check_label}.', '',
             ATTRIBUTION, '', 'Paths are relative to the original run directory.', '',
             'Graph exports [SVG](graph.svg) · [GraphML](graph.graphml) · [JSON](graph.json).']
    for section in ('observed', 'possible'):
        lines.extend(['', f'## {section.capitalize()} evidence', ''])
        for node in evidence[section]:
            ref = node['source_ref']
            diagnostic = f' · `{node["diagnostic_ref"]}`' if 'diagnostic_ref' in node else ''
            lines.append(f'- {node["label"]} · `{ref}`{diagnostic}')
    if warnings:
        lines.extend(['', '## Evidence gaps', '', *(f'- {warning}' for warning in warnings)])
    (output / 'analysis.md').write_text('\n'.join(lines) + '\n')
    return report
