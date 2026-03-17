import aiohttp
import asyncio
import logging
from bs4 import BeautifulSoup
from blacklist import get_blacklist

async def parse_gift_owner(session: aiohttp.ClientSession, url: str) -> str | None:
    try:
        async with session.get(url, timeout=10, allow_redirects=False) as response:
            if response.status != 200:
                return None
            html = await response.text()
            soup = BeautifulSoup(html, "lxml")
            
            owner_tag = soup.select_one('table.tgme_gift_table th:-soup-contains("Owner") + td a')
            if owner_tag and owner_tag.get('href'):
                username = owner_tag['href'].replace('https://t.me/', '')
                return f"@{username}"
            
            owner_link = soup.find('a', href=lambda x: x and x.startswith('https://t.me/') and not any(
                skip in x for skip in ['nft', 'gift', 'joinchat']))
            if owner_link:
                username = owner_link['href'].replace('https://t.me/', '')
                return f"@{username}"
                
            return None
    except Exception as e:
        logging.debug(f"Ошибка парсинга {url}: {e}")
        return None

async def find_real_owners(urls: list, limit: int = 20) -> list:
    blacklist = await get_blacklist()
    
    async with aiohttp.ClientSession() as session:
        tasks = [parse_gift_owner(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        found = []
        for i, owner in enumerate(results):
            if owner and len(found) < limit:
                if owner.lower() in blacklist:
                    continue
                found.append({
                    'url': urls[i],
                    'owner': owner
                })
        return found