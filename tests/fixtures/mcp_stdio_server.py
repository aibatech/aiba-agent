"""Deterministic JSON-RPC server fixture; never opens sockets or calls models."""
import json
import sys


def main():
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request:
            continue  # e.g. notifications/initialized
        method = request.get('method')
        if method == 'initialize':
            result = {
                'protocolVersion': request['params']['protocolVersion'],
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'aiba-test-fixture', 'version': '1.0'},
            }
        elif method == 'tools/list':
            result = {'tools': [{
                'name': 'ping', 'description': 'Return fixture text',
                'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}},
                                'required': ['text'], 'additionalProperties': False},
            }]}
        elif method == 'tools/call':
            args = request['params'].get('arguments', {})
            result = {'content': [{'type': 'text', 'text': 'fixture-pong:' + str(args.get('text', ''))}],
                      'isError': args.get('text') == 'error'}
        elif method == 'ping':
            result = {}
        else:
            print(json.dumps({'jsonrpc': '2.0', 'id': request['id'],
                              'error': {'code': -32601, 'message': 'Unknown method'}}), flush=True)
            continue
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)


if __name__ == '__main__':
    main()
