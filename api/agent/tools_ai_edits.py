"""AI-edit import: bring a file an AI tool made into the library, linked to its original."""
from typing import Annotated, Literal, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from api.agent.internal_client import InternalClient
from api.agent.runtime import run_tool
from api.agent.tools_common import register_tool
from api.agent.tools_write import WRITE_TOOL_LEVELS

ImportPath = Annotated[str, Field(min_length=1, max_length=4096)]
# A second call imports a second revision, so the tool is not idempotent; it never overwrites a file.
IMPORT_ANNOTATIONS = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                     idempotent_hint=False, open_world_hint=False)


def register_ai_edit_tools(server: MCPServer, client: InternalClient) -> None:
    async def import_ai_edit(ctx: Context, original_path: ImportPath, source_file: ImportPath,
                             mode: Literal['move', 'copy'], tool: Annotated[str, Field(min_length=1, max_length=64)],
                             model: Annotated[Optional[str], Field(max_length=200)] = None,
                             note: Annotated[Optional[str], Field(max_length=1000)] = None) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await client.call(grant, 'import_ai_edit', json={
                'original_path': original_path, 'source_file': source_file, 'mode': mode,
                'tool': tool, 'model': model, 'note': note,
            }, timeout=settings['call_timeout_s'])
        return await run_tool(ctx, 'import_ai_edit', handler, write=True)

    register_tool(
        server, import_ai_edit, 'import_ai_edit',
        'Bring a file an AI tool made from a library photo into the library, linked to that photo. '
        '`original_path` is the library photo; `source_file` is the edit on the server\'s disk (absolute path, '
        'a rendered image, not already a library photo). `mode` is required: `move` deletes the source after '
        'the copy is verified, `copy` keeps it. `tool` must be a key of the server\'s `ai_edits.tool_suffixes` '
        '(by default `antigravity-gemini` → agy, `openai-chatgpt` → gpt, `anthropic-claude` → ant; '
        'an unknown name is refused with the configured list); the file lands beside the original as `{name}_{suffix}_{revision}{ext}`, '
        'never over an existing file. The new file is scanned when scanning is enabled (`scan.started`); '
        'otherwise it appears after the next scan. `get_photo` on the edit returns `ai_edit_of`. '
        'Not idempotent: each call adds a revision.',
        IMPORT_ANNOTATIONS, WRITE_TOOL_LEVELS['import_ai_edit'])
