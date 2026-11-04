"""AI-edit import: bring a file an AI tool made into the library, linked to its original."""
import asyncio
import time
from typing import Annotated, Optional
from urllib.parse import quote

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from api.agent.internal_client import InternalClient
from api.agent.runtime import run_tool
from api.agent.tools_common import register_tool
from api.agent.tools_write import WRITE_TOOL_LEVELS
from api.models.ai_edits import MAX_IMAGE_DATA_CHARS

ImportPath = Annotated[str, Field(min_length=1, max_length=4096)]
# A second call imports a second revision, so the tool is not idempotent. It is additive only: it
# writes one new file under a free name and never deletes, moves or overwrites a file (the image
# comes as bytes, or is read from the drop folder and left there), hence destructive_hint=False.
IMPORT_ANNOTATIONS = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                     idempotent_hint=False, open_world_hint=False)
# How long the tool waits for the edit's scan, so the assistant can confirm the photo is in
# Facet instead of guessing; a slower scan answers ready=false and the edit shows up later.
READY_WAIT_S = 180
READY_POLL_S = 3


def _scan_state_for(path: str) -> tuple[bool, bool]:
    """(scan job still running, edit's photo row exists)."""
    from api.database import get_db
    from api.routers.scan import _scan_state

    with get_db() as conn:
        exists = conn.execute('SELECT 1 FROM photos WHERE path = ?', (path,)).fetchone() is not None
    return bool(_scan_state.get('running')), exists


async def _wait_until_ready(path: str) -> bool:
    """True once the scan job is over and the edit is a photo (scored, grouped, captioned)."""
    # The import marks the scan job running before it answers, so "not running" means
    # the job is over: the photo either made it or the scan failed.
    deadline = time.monotonic() + READY_WAIT_S
    while True:
        running, exists = await asyncio.to_thread(_scan_state_for, path)
        if not running:
            return exists
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(READY_POLL_S)


def register_ai_edit_tools(server: MCPServer, client: InternalClient) -> None:
    async def import_ai_edit(ctx: Context, original_path: ImportPath,
                             tool: Annotated[str, Field(min_length=1, max_length=64)],
                             source_file: Annotated[Optional[str], Field(min_length=1, max_length=4096)] = None,
                             image_data: Annotated[Optional[str],
                                                   Field(min_length=1, max_length=MAX_IMAGE_DATA_CHARS)] = None,
                             model: Annotated[Optional[str], Field(max_length=200)] = None,
                             note: Annotated[Optional[str], Field(max_length=1000)] = None) -> CallToolResult:
        async def handler(grant, resolved, settings):
            result = await client.call(grant, 'import_ai_edit', json={
                'original_path': original_path, 'source_file': source_file, 'image_data': image_data,
                'tool': tool, 'model': model, 'note': note,
            }, timeout=settings['call_timeout_s'])
            data = result.get('data') if result.get('ok') else None
            if not isinstance(data, dict):
                return result
            edit_path = data['edit_path']
            data['ready'] = bool(data['scan']['started']) and await _wait_until_ready(edit_path)
            data['photo_page'] = '/photo?path=' + quote(edit_path, safe='')
            if data['ready']:
                photo = await client.call(grant, 'get_photo', query={'path': edit_path},
                                          timeout=settings['call_timeout_s'])
                if photo.get('ok') and isinstance(photo.get('data'), dict):
                    data['caption'] = photo['data'].get('caption')
            return result
        return await run_tool(ctx, 'import_ai_edit', handler, write=True)

    register_tool(
        server, import_ai_edit, 'import_ai_edit',
        'Bring an image an AI tool made from a library photo into the library, linked to that photo. '
        '`original_path` is the library photo. Send the edit as bytes, exactly one of: `source_file`, the name of '
        'a file you saved in the AI-edit drop folder on the Facet server (`ai_edits.drop_dir`; `edit_photo` '
        'names it), or `image_data`, the image base64-encoded (at most 50 MB decoded). A rendered image (JPEG, '
        'PNG, WebP, TIFF...), not a RAW. Facet writes its own copy and never deletes or changes your file: '
        'remove your work file yourself once the import succeeds. `tool` must be a key of the server\'s `ai_edits.tool_suffixes` '
        '(by default `antigravity-gemini` → agy, `openai-chatgpt` → gpt, `anthropic-claude` → ant; '
        'an unknown name is refused with the configured list); the file lands beside the original as `{name}_{suffix}_{revision}{ext}`, '
        'never over an existing file. The new file is scanned when scanning is enabled (`scan.started`); '
        'otherwise it appears after the next scan. `get_photo` on the edit returns `ai_edit_of`. '
        '`note` is one line on what changed (e.g. "removed watch from left wrist"); once scanned, the edit\'s '
        'caption is the original\'s caption followed by "AI: <note>". '
        'The call waits for that scan (up to 3 minutes) and answers `ready: true` only once the edit is in '
        'Facet, with its `caption` and `photo_page` (a path on the Facet server): tell the user it is ready '
        'only then. `ready: false` means it is placed and linked and will appear when the scan finishes. '
        'Not idempotent: each call adds a revision.',
        IMPORT_ANNOTATIONS, WRITE_TOOL_LEVELS['import_ai_edit'])
