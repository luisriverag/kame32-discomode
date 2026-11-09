import asyncio
import sys
from urllib.request import urlopen

if sys.argv[1] == 'mcp':
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def check():
        async with streamablehttp_client('http://127.0.0.1:8000/mcp') as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool('get_status', {})
                if result.isError:
                    raise RuntimeError('MCP app connectivity check failed')

    asyncio.run(check())
else:
    with urlopen('http://127.0.0.1:5000/', timeout=5) as response:
        if response.status != 200:
            raise RuntimeError('App is not ready')
