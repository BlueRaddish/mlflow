"""Execute the actual public example and prove its local package origin."""
import argparse
import inspect
from pathlib import Path
import textwrap


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['ms-evening'], required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--response-type', choices=['chat', 'agent'], required=True)
    parser.add_argument('--mode', choices=['example', 'normal-control'], required=True)
    args = parser.parse_args()
    from agent_framework import AgentResponse, ChatResponse, Message
    import agent_framework._types as types

    source = Path(args.source).resolve()
    response_type = ChatResponse if args.response_type == 'chat' else AgentResponse
    assert Path(types.__file__).resolve() == source / 'python/packages/core/agent_framework/_types.py'
    if args.mode == 'normal-control':
        response = response_type(messages=[Message('assistant', ['Hello'])])
        assert response.text == 'Hello'
        assert response_type.from_updates(response.to_updates()).text == 'Hello'
    else:
        doc = inspect.getdoc(response_type.to_updates)
        assert doc and doc.count('.. code-block:: python') == 1
        snippet = textwrap.dedent(doc.split('.. code-block:: python', 1)[1]).strip()
        assert snippet, 'An empty example is not a passing check.'
        namespace = {}
        exec(compile(snippet, response_type.__name__ + '.to_updates actual docstring', 'exec'), namespace)
        assert namespace['response'].text == 'Hello'
        assert response_type.from_updates(namespace['response'].to_updates()).text == 'Hello'
    print('ACTUAL_CONSUMER_CHECK=' + args.response_type + ':' + args.mode + ':passed:origin=' + str(types.__file__))


if __name__ == '__main__':
    main()
