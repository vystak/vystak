"""Code generation for the ResponsesHandler class embedded in generated servers.

The generated ``ResponsesHandler`` owns the OpenAI Responses API semantics
(create / create_stream / get) in a form that is independent of the HTTP
transport. The FastAPI ``/v1/responses`` routes are reduced to thin adapters
that delegate into this handler; Task 4b will plug the same handler into the
non-HTTP transport listener via ``ServerDispatcher``.

Wire format (SSE event shapes, ``response.*`` event types, error envelopes)
is preserved exactly — this is a mechanical extraction.
"""

from vystak.schema.agent import Agent


def _uses_persistent_store(agent: Agent) -> bool:
    """Whether the agent uses a persistent (postgres/sqlite) session store.

    Delegates to ``templates._get_session_store`` via a lazy import so we
    match the canonical lookup logic exactly without creating an import
    cycle (``templates`` imports from this module).
    """
    from vystak_adapter_langchain.templates import _get_session_store

    session_store = _get_session_store(agent)
    return bool(session_store and session_store.engine in ("postgres", "sqlite"))


def generate_responses_handler_code(agent: Agent) -> str:
    """Emit the ``ResponsesHandler`` class as a Python source string.

    The generated class has three coroutine methods:

      * ``create(body, metadata)`` — non-streaming (sync or background) path.
        Returns a ``ResponseObject.model_dump()`` dict.
      * ``create_stream(body, metadata)`` — async-iterator of SSE chunks (each
        a plain dict; the caller is responsible for ``json.dumps`` + ``data:``
        framing).
      * ``get(response_id)`` — returns the stored response dict or ``None``.

    The class accesses LangGraph's compiled graph via ``self._graph`` and the
    in-memory response map via ``self._response_store``. Memory-action hooks
    (``handle_memory_actions`` + ``_store``) are looked up at the module level
    — they're only emitted when the agent uses a persistent session store.

    Errors that the previous inline routes signalled via HTTP status codes
    (404 for unknown ``previous_response_id``, 400 for chaining off an
    unstored response) are raised as ``fastapi.HTTPException`` from the
    handler. The route adapter reraises; a non-HTTP listener (Task 4b) can
    catch and translate to its own error envelope.
    """
    # ``agent_ref`` is always ``_agent`` in the current template (all four
    # shapes — persistent / mcp combinations — assign to ``_agent``), so we
    # can emit it as a plain literal and keep this module free of the
    # branching logic in ``templates.generate_server_py``.
    uses_persistent = _uses_persistent_store(agent)
    agent_ref = "_agent"

    lines: list[str] = []

    lines.append("# === ResponsesHandler ===")
    lines.append("from fastapi import HTTPException as _ResponsesHTTPException")
    lines.append("")
    lines.append("")
    lines.append("class ResponsesHandler:")
    lines.append('    """Dispatches OpenAI Responses API calls to the agent\'s LangGraph.')
    lines.append("")
    lines.append("    Shared by the FastAPI ``/v1/responses`` routes and (in Task 4b) by the")
    lines.append("    transport listener for non-HTTP transports. Wire format is preserved:")
    lines.append("    the streaming path yields the exact same ``response.*`` event dicts as")
    lines.append("    the previous inline handler.")
    lines.append('    """')
    lines.append("")
    lines.append("    def __init__(self, graph, response_store):")
    lines.append("        self._graph = graph")
    lines.append("        self._response_store = response_store")
    lines.append("")

    # --- create (sync + background) ---------------------------------------
    lines.append("    async def create(self, body: dict, metadata: dict | None = None) -> dict:")
    lines.append('        """Handle a non-streaming /v1/responses create call.')
    lines.append("")
    lines.append("        ``body`` is the ``CreateResponseRequest.model_dump()`` dict. Returns")
    lines.append("        the ``ResponseObject.model_dump()`` dict (or an in-progress stub if")
    lines.append("        ``body['background']`` is true). Raises ``HTTPException`` for the")
    lines.append("        previously inline 404 / 400 error paths.")
    lines.append('        """')
    lines.append("        user_id = body.get('user_id')")
    lines.append("        project_id = body.get('project_id')")
    lines.append("        store = body.get('store', True)")
    lines.append("        previous_id = body.get('previous_response_id')")
    lines.append("")
    lines.append("        # Parse input into messages")
    lines.append("        input_messages = []")
    if uses_persistent:
        lines.append("        last_user_msg = ''")
    lines.append("        raw_input = body.get('input')")
    lines.append("        if isinstance(raw_input, str):")
    lines.append("            input_messages.append(('user', raw_input))")
    if uses_persistent:
        lines.append("            last_user_msg = raw_input")
    lines.append("        elif raw_input is not None:")
    lines.append("            for item in raw_input:")
    lines.append("                if isinstance(item, dict):")
    lines.append(
        "                    input_messages.append((item.get('role', 'user'), item.get('content', '')))"
    )
    if uses_persistent:
        lines.append("                    if item.get('role') == 'user' and item.get('content'):")
        lines.append("                        last_user_msg = item['content']")
    lines.append("                elif hasattr(item, 'role'):")
    lines.append("                    input_messages.append((item.role, item.content or ''))")
    if uses_persistent:
        lines.append("                    if item.role == 'user' and item.content:")
        lines.append("                        last_user_msg = item.content")
    lines.append("")
    lines.append("        # Determine thread_id and response_id")
    lines.append("        if previous_id:")
    lines.append("            if previous_id not in self._response_store:")
    lines.append("                raise _ResponsesHTTPException(")
    lines.append("                    status_code=404,")
    lines.append("                    detail=ErrorResponse(error=ErrorDetail(")
    lines.append("                        message=f\"Response '{previous_id}' not found\",")
    lines.append('                        type="invalid_request_error", code="response_not_found",')
    lines.append("                    )).model_dump(),")
    lines.append("                )")
    lines.append("            prev = self._response_store[previous_id]")
    lines.append("            if not prev.get('stored'):")
    lines.append("                raise _ResponsesHTTPException(")
    lines.append("                    status_code=400,")
    lines.append("                    detail=ErrorResponse(error=ErrorDetail(")
    lines.append(
        '                        message="Cannot chain from a response created with store=false",'
    )
    lines.append('                        type="invalid_request_error", code="invalid_value",')
    lines.append("                    )).model_dump(),")
    lines.append("                )")
    lines.append("            thread_id = prev.get('thread_id', str(uuid.uuid4()))")
    lines.append("            response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("        elif store:")
    lines.append("            response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("            thread_id = response_id")
    lines.append("        else:")
    lines.append("            response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("            thread_id = str(uuid.uuid4())")
    lines.append("")
    lines.append('        config = {"configurable": {')
    lines.append('            "thread_id": thread_id,')
    lines.append('            "user_id": user_id,')
    lines.append('            "project_id": project_id,')
    lines.append('            "agent_name": AGENT_NAME,')
    lines.append("        }}")
    lines.append("")
    # Background branch
    lines.append("        if body.get('background'):")
    lines.append("            self._response_store[response_id] = {")
    lines.append("                'id': response_id,")
    lines.append("                'status': 'in_progress',")
    lines.append("                'output': [],")
    lines.append("                'model': MODEL_ID,")
    lines.append("                'stored': store,")
    lines.append("                'thread_id': thread_id,")
    lines.append("                'created_at': int(time.time()),")
    lines.append("            }")
    lines.append("            asyncio.create_task(")
    lines.append(
        "                self._run_background(input_messages, config, response_id, user_id, project_id)"
    )
    lines.append("            )")
    lines.append("            return ResponseObject(")
    lines.append("                id=response_id,")
    lines.append('                status="in_progress",')
    lines.append("                output=[],")
    lines.append("                model=MODEL_ID,")
    lines.append("                created_at=int(time.time()),")
    lines.append("            ).model_dump()")
    lines.append("")
    # Synchronous invoke (delegates to shared one-shot core)
    lines.append("        metadata = {")
    lines.append('            "sessionId": thread_id,')
    lines.append('            "user_id": user_id,')
    lines.append('            "project_id": project_id,')
    lines.append("        }")
    lines.append("        turn = await process_turn('', metadata, messages=input_messages)")
    lines.append("        response_text = turn.response_text")
    lines.append("        # TODO: surface usage_metadata via TurnResult — currently zero.")
    lines.append("        usage_obj = None")
    lines.append("")
    lines.append(
        "        output = [ResponseOutput(type='message', role='assistant', content=response_text)]"
    )
    lines.append("        resp = ResponseObject(")
    lines.append("            id=response_id,")
    lines.append('            status="completed",')
    lines.append("            output=output,")
    lines.append("            model=MODEL_ID,")
    lines.append("            usage=usage_obj,")
    lines.append("            created_at=int(time.time()),")
    lines.append("        )")
    lines.append("        if store:")
    lines.append("            self._response_store[response_id] = {")
    lines.append("                'id': response_id,")
    lines.append("                'status': 'completed',")
    lines.append("                'output': output,")
    lines.append("                'model': MODEL_ID,")
    lines.append("                'usage': usage_obj,")
    lines.append("                'stored': True,")
    lines.append("                'thread_id': thread_id,")
    lines.append("                'created_at': int(time.time()),")
    lines.append("                'response': resp.model_dump(),")
    lines.append("            }")
    lines.append("        return resp.model_dump()")
    lines.append("")

    # --- _run_background --------------------------------------------------
    lines.append("    async def _run_background(")
    lines.append("        self, input_messages, config, response_id, user_id, project_id")
    lines.append("    ):")
    lines.append('        """Background execution path — mutates response_store in place."""')
    lines.append("        try:")
    lines.append("            # Sync background invoke (delegates to shared one-shot core)")
    lines.append("            metadata = {")
    lines.append('                "sessionId": config["configurable"].get("thread_id"),')
    lines.append('                "user_id": user_id,')
    lines.append('                "project_id": project_id,')
    lines.append("            }")
    lines.append("            turn = await process_turn(")
    lines.append("                '', metadata,")
    lines.append("                messages=input_messages, task_id=response_id,")
    lines.append("            )")
    lines.append("            response_text = turn.response_text")
    lines.append("            # TODO: surface usage_metadata via TurnResult — currently zero.")
    lines.append("            usage_obj = None")
    lines.append(
        "            output = [ResponseOutput(type='message', role='assistant', content=response_text)]"
    )
    lines.append("            self._response_store[response_id].update({")
    lines.append("                'status': 'completed',")
    lines.append("                'output': output,")
    lines.append("                'usage': usage_obj,")
    lines.append("            })")
    lines.append("        except Exception as exc:")
    lines.append("            self._response_store[response_id].update({")
    lines.append("                'status': 'failed',")
    lines.append("                'error': str(exc),")
    lines.append("            })")
    lines.append("")

    # --- get --------------------------------------------------------------
    lines.append("    async def get(self, response_id: str) -> dict | None:")
    lines.append('        """Return stored response dict for ``response_id`` or ``None``."""')
    lines.append("        if response_id not in self._response_store:")
    lines.append("            return None")
    lines.append("        stored = self._response_store[response_id]")
    lines.append("        if 'response' in stored:")
    lines.append("            return stored['response']")
    lines.append("        return ResponseObject(")
    lines.append("            id=stored['id'],")
    lines.append("            status=stored['status'],")
    lines.append("            output=stored.get('output', []),")
    lines.append("            model=stored.get('model', MODEL_ID),")
    lines.append("            usage=stored.get('usage'),")
    lines.append("            created_at=stored.get('created_at', 0),")
    lines.append("        ).model_dump()")
    lines.append("")

    # --- create_stream ----------------------------------------------------
    lines.append("    async def create_stream(self, body: dict, metadata: dict | None = None):")
    lines.append('        """Async-iterator over Responses API SSE event dicts.')
    lines.append("")
    lines.append("        Each yielded value is the chunk payload (already-structured dict or")
    lines.append('        the sentinel string ``"[DONE]"``). The caller frames it for the')
    lines.append("        wire (``EventSourceResponse`` wraps with ``data: json.dumps(chunk)``).")
    lines.append('        """')
    lines.append("        user_id = body.get('user_id')")
    lines.append("        project_id = body.get('project_id')")
    lines.append("        store = body.get('store', True)")
    lines.append("        previous_id = body.get('previous_response_id')")
    lines.append("")
    lines.append("        # Parse input into messages")
    lines.append("        input_messages = []")
    lines.append("        raw_input = body.get('input')")
    lines.append("        if isinstance(raw_input, str):")
    lines.append("            input_messages.append(('user', raw_input))")
    lines.append("        elif raw_input is not None:")
    lines.append("            for item in raw_input:")
    lines.append("                if isinstance(item, dict):")
    lines.append(
        "                    input_messages.append((item.get('role', 'user'), item.get('content', '')))"
    )
    lines.append("                elif hasattr(item, 'role'):")
    lines.append("                    input_messages.append((item.role, item.content or ''))")
    lines.append("")
    lines.append("        # Determine thread_id and response_id")
    lines.append("        if previous_id:")
    lines.append("            if previous_id not in self._response_store:")
    lines.append("                raise _ResponsesHTTPException(")
    lines.append("                    status_code=404,")
    lines.append("                    detail=ErrorResponse(error=ErrorDetail(")
    lines.append("                        message=f\"Response '{previous_id}' not found\",")
    lines.append('                        type="invalid_request_error", code="response_not_found",')
    lines.append("                    )).model_dump(),")
    lines.append("                )")
    lines.append("            prev = self._response_store[previous_id]")
    lines.append("            if not prev.get('stored'):")
    lines.append("                raise _ResponsesHTTPException(")
    lines.append("                    status_code=400,")
    lines.append("                    detail=ErrorResponse(error=ErrorDetail(")
    lines.append(
        '                        message="Cannot chain from a response created with store=false",'
    )
    lines.append('                        type="invalid_request_error", code="invalid_value",')
    lines.append("                    )).model_dump(),")
    lines.append("                )")
    lines.append("            thread_id = prev.get('thread_id', str(uuid.uuid4()))")
    lines.append("            response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("        elif store:")
    lines.append("            response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("            thread_id = response_id")
    lines.append("        else:")
    lines.append("            response_id = f'resp-{uuid.uuid4().hex[:16]}'")
    lines.append("            thread_id = str(uuid.uuid4())")
    lines.append("")
    lines.append('        config = {"configurable": {')
    lines.append('            "thread_id": thread_id,')
    lines.append('            "user_id": user_id,')
    lines.append('            "project_id": project_id,')
    lines.append('            "agent_name": AGENT_NAME,')
    lines.append("        }}")
    lines.append("")
    # Begin streaming body (previously _stream_response inner event_generator)
    lines.append("        created_at = int(time.time())")
    lines.append("        # response.created")
    lines.append("        yield {")
    lines.append('            "type": "response.created",')
    lines.append('            "response": {')
    lines.append('                "id": response_id,')
    lines.append('                "status": "in_progress",')
    lines.append('                "output": [],')
    lines.append('                "model": MODEL_ID,')
    lines.append('                "created_at": created_at,')
    lines.append("            },")
    lines.append("        }")
    lines.append("")
    lines.append("        output_index = 0")
    lines.append("        accumulated = []")
    lines.append("        pending_tool_calls = {}")
    lines.append(
        "        tool_messages_for_memory = []  # Collect tool messages for memory processing"
    )
    lines.append("        final_output = []")
    lines.append("")
    lines.append("        # response.output_item.added (message)")
    lines.append("        yield {")
    lines.append('            "type": "response.output_item.added",')
    lines.append('            "output_index": output_index,')
    lines.append('            "item": {"type": "message", "role": "assistant", "content": []},')
    lines.append("        }")
    lines.append("")
    lines.append("        # response.content_part.added")
    lines.append("        yield {")
    lines.append('            "type": "response.content_part.added",')
    lines.append('            "output_index": output_index,')
    lines.append('            "content_index": 0,')
    lines.append('            "part": {"type": "output_text", "text": ""},')
    lines.append("        }")
    lines.append("")
    lines.append(f"        async for chunk in {agent_ref}.astream(")
    lines.append('            {"messages": input_messages},')
    lines.append("            config=config,")
    lines.append('            stream_mode=["messages", "custom"],')
    lines.append("        ):")
    lines.append('            if chunk[0] == "messages":')
    lines.append("                msg, _md = chunk[1]")
    lines.append('                if msg.type == "AIMessageChunk":')
    lines.append("                    if msg.content:")
    lines.append(
        "                        text = msg.content if isinstance(msg.content, str) else ''"
    )
    lines.append("                        if not text and isinstance(msg.content, list):")
    lines.append("                            for block in msg.content:")
    lines.append(
        "                                if isinstance(block, dict) and block.get('type') == 'text':"
    )
    lines.append("                                    text += block.get('text', '')")
    lines.append("                        if text:")
    lines.append("                            accumulated.append(text)")
    lines.append("                            yield {")
    lines.append('                                "type": "response.output_text.delta",')
    lines.append('                                "output_index": output_index,')
    lines.append('                                "content_index": 0,')
    lines.append('                                "delta": text,')
    lines.append("                            }")
    lines.append("                    if msg.tool_call_chunks:")
    lines.append("                        for tc in msg.tool_call_chunks:")
    lines.append("                            tc_id = tc.get('id') or tc.get('index', '')")
    lines.append("                            if tc.get('name'):")
    lines.append("                                output_index += 1")
    lines.append("                                pending_tool_calls[str(tc_id)] = {")
    lines.append("                                    'name': tc['name'],")
    lines.append("                                    'args': '',")
    lines.append("                                    'output_index': output_index,")
    lines.append("                                }")
    lines.append("                                yield {")
    lines.append('                                    "type": "response.output_item.added",')
    lines.append('                                    "output_index": output_index,')
    lines.append(
        '                                    "item": {"type": "function_call", "name": tc["name"], "call_id": str(tc_id)},'
    )
    lines.append("                                }")
    lines.append("                            if tc.get('args'):")
    lines.append("                                key = str(tc_id)")
    lines.append("                                if key in pending_tool_calls:")
    lines.append(
        "                                    pending_tool_calls[key]['args'] += tc['args']"
    )
    lines.append("                                yield {")
    lines.append(
        '                                    "type": "response.function_call_arguments.delta",'
    )
    lines.append(
        '                                    "output_index": pending_tool_calls.get(key, {}).get("output_index", output_index),'
    )
    lines.append('                                    "delta": tc["args"],')
    lines.append("                                }")
    lines.append('                elif msg.type == "tool":')
    lines.append("                    # Close pending tool call")
    lines.append("                    tool_call_id = getattr(msg, 'tool_call_id', None)")
    lines.append("                    if tool_call_id and str(tool_call_id) in pending_tool_calls:")
    lines.append("                        tc_info = pending_tool_calls.pop(str(tool_call_id))")
    lines.append("                        yield {")
    lines.append('                            "type": "response.function_call_arguments.done",')
    lines.append('                            "output_index": tc_info["output_index"],')
    lines.append('                            "arguments": tc_info["args"],')
    lines.append("                        }")
    lines.append("                    # Emit tool output")
    lines.append("                    output_index += 1")
    lines.append("                    yield {")
    lines.append('                        "type": "response.output_item.added",')
    lines.append('                        "output_index": output_index,')
    lines.append('                        "item": {')
    lines.append('                            "type": "function_call_output",')
    lines.append('                            "call_id": str(getattr(msg, "tool_call_id", "")),')
    lines.append(
        '                            "output": str(msg.content)[:500] if msg.content else "",'
    )
    lines.append("                        },")
    lines.append("                    }")
    lines.append("                    tool_messages_for_memory.append(msg)")
    lines.append("")
    lines.append("        # response.output_text.done")
    lines.append("        full_text = ''.join(accumulated)")
    lines.append("        yield {")
    lines.append('            "type": "response.output_text.done",')
    lines.append('            "output_index": 0,')
    lines.append('            "content_index": 0,')
    lines.append('            "text": full_text,')
    lines.append("        }")
    lines.append("")
    lines.append(
        "        final_output = [ResponseOutput(type='message', role='assistant', content=full_text)]"
    )
    lines.append("")
    lines.append("        # response.completed")
    lines.append("        yield {")
    lines.append('            "type": "response.completed",')
    lines.append('            "response": {')
    lines.append('                "id": response_id,')
    lines.append('                "status": "completed",')
    lines.append(
        '                "output": [o.model_dump() if hasattr(o, "model_dump") else o for o in final_output],'
    )
    lines.append('                "model": MODEL_ID,')
    lines.append('                "created_at": created_at,')
    lines.append("            },")
    lines.append("        }")
    lines.append("")
    lines.append("        if store:")
    lines.append("            self._response_store[response_id] = {")
    lines.append("                'id': response_id,")
    lines.append("                'status': 'completed',")
    lines.append("                'output': final_output,")
    lines.append("                'model': MODEL_ID,")
    lines.append("                'stored': True,")
    lines.append("                'thread_id': config['configurable']['thread_id'],")
    lines.append("                'created_at': created_at,")
    lines.append("            }")
    if uses_persistent:
        lines.append("")
        lines.append("        # Process memory actions from tool messages")
        lines.append("        if tool_messages_for_memory:")
        lines.append(
            "            await handle_memory_actions(_store, tool_messages_for_memory, user_id=user_id, project_id=project_id)"
        )
    lines.append("")
    lines.append('        yield "[DONE]"')
    lines.append("")

    return "\n".join(lines)
