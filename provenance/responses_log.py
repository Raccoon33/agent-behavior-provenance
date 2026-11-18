"""Read the CSV experiment harness's Responses JSONL, preserving line references."""

import json
from dataclasses import dataclass

from .schema import Event


@dataclass
class ToolExchange:
    call: Event
    result: Event
    arguments: dict
    output: dict


@dataclass
class Session:
    events: list[Event]
    exchanges: list[ToolExchange]
    prompt: str
    warnings: list[str]


def read_session(run, filename, session_name):
    events, exchanges, warnings = [], [], []
    pending, seen = {}, set()
    prompt = ''
    turn_id = ''

    def emit(kind, ref, **fields):
        order = len(events) + 1
        event = Event(f'{session_name}:e{order:05d}', order, kind, ref, **fields)
        events.append(event)
        return event

    for number, raw in enumerate((run / filename).read_bytes().splitlines(), 1):
        if not raw.strip():
            continue
        ref = f'{filename}:line-{number}'
        try:
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError('expected an object')
            kind = record.get('kind')
            if kind == 'initial_prompt':
                if events or not isinstance(record.get('content'), str):
                    raise ValueError('invalid or misplaced initial prompt')
                prompt = record['content']
                emit('initial_prompt', ref)
            elif kind == 'response':
                body = record['body']
                if not isinstance(body, dict) or not isinstance(body.get('output'), list):
                    raise ValueError('response output must be an array')
                turn_id = ref
                emit('model_turn', ref, turn_id=turn_id)
                for index, item in enumerate(body['output']):
                    item_ref = f'{ref}:/body/output/{index}'
                    if not isinstance(item, dict):
                        warnings.append(f'{item_ref}: expected an output object')
                        continue
                    if item.get('type') != 'function_call':
                        continue
                    call_id, name = item.get('call_id'), item.get('name')
                    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                        warnings.append(f'{item_ref}: missing call identity')
                        continue
                    if call_id in seen:
                        pending.pop(call_id, None)
                        warnings.append(f'{item_ref}: duplicate call ID')
                        continue
                    seen.add(call_id)
                    try:
                        args = json.loads(item.get('arguments', ''))
                    except (ValueError, TypeError):
                        args = None
                    path = args.get('path', '') if isinstance(args, dict) else ''
                    call = emit('tool_call', item_ref, tool_name=name, call_id=call_id,
                                turn_id=turn_id, path=path if isinstance(path, str) else '')
                    pending[call_id] = (call, args)
            elif kind == 'tool':
                call, args = pending.pop(record['call_id'], (None, None))
                output = record.get('result')
                if (call is None or call.turn_id != turn_id or call.tool_name != record.get('name')
                        or not isinstance(args, dict) or record.get('arguments') != args
                        or not isinstance(output, dict)):
                    warnings.append(f'{ref}: tool result has no matching model call and arguments')
                    continue
                code = output.get('exit_code')
                result = emit('tool_result', ref, tool_name=call.tool_name, call_id=call.call_id,
                              turn_id=call.turn_id, path=call.path,
                              status='error' if 'error' in output else 'recorded',
                              exit_code=code if type(code) is int else None)
                exchanges.append(ToolExchange(call, result, args, output))
            elif kind == 'error':
                emit('execution_error', ref, status='error')
            else:
                warnings.append(f'{ref}: unsupported record kind')
        except (ValueError, UnicodeError, TypeError, KeyError):
            warnings.append(f'{ref}: malformed record')

    warnings.extend(f'{call.source_ref}: no matching broker result' for call, _ in pending.values())
    if not any(event.kind == 'model_turn' for event in events):
        warnings.append(f'{filename}: no response records parsed')
    return Session(events, exchanges, prompt, warnings)
