#!/usr/bin/env python3
"""
GPSS Patent Representative Figure & Images Scraper.
Extracts absolute figure URLs for a given patent number from TIPO GPSS headlessly.
"""

import sys
import asyncio
import httpx
import re
import random

async def get_gpss_figures(patent_no: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        # Step 1: Establish portal session
        print("[1/5] Establishing Portal Session...")
        await client.get("https://tiponet.tipo.gov.tw/030_OUT_V1/home.do")
        
        # Step 2: Establish GPSS session
        print("[2/5] Establishing GPSS Session...")
        await client.get("https://tiponet.tipo.gov.tw/gpss2/")
        
        # Step 3: Fetch search page and bypass client-side JavaScript random redirect
        print("[3/5] Navigating to GPSS search page...")
        rand_val = random.random()
        gpss_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/gpssbkm?@@{rand_val}"
        res = await client.get(gpss_url)
        
        # Extract session validation INFO parameter
        m_info = re.search(r'name=["\']?INFO["\']?\s+value=["\']?([A-Za-z0-9]+)["\']?', res.text, re.IGNORECASE)
        if not m_info:
            m_info = re.search(r'value=["\']?([A-Za-z0-9]+)["\']?\s+name=["\']?INFO["\']?', res.text, re.IGNORECASE)
            
        if not m_info:
            print("[-] Error: Failed to retrieve INFO token from GPSS session.")
            return []
        
        info_val = m_info.group(1)
        
        # Extract POST submission URL
        m_action = re.search(r'action=["\']?(/gpss[12]/gpsskmc/gpssbkm[^\'"]*)["\']?', res.text, re.IGNORECASE)
        action_path = m_action.group(1) if m_action else '/gpss2/gpsskmc/gpssbkm'
        action_url = f"https://tiponet.tipo.gov.tw{action_path}"
        
        # Step 4: Submit search query
        print(f"[4/5] Searching for patent: {patent_no}...")
        data = {
            "INFO": info_val,
            "@_21_1_T": "T_XX",
            "_21_1_T": patent_no,
            "@_0_9_T": "T_XX",
            "_0_9_T": "",
            "_IMG_檢索.x": "25",
            "_IMG_檢索.y": "25"
        }
        res = await client.post(action_url, data=data)
        
        # Follow HTML refresh tags if returned by server
        m_refresh = re.search(r'CONTENT=["\']?0;\s*URL=([^"\'>\s]+)["\']?', res.text, re.IGNORECASE)
        if m_refresh:
            redirect_url = m_refresh.group(1).strip("'\"")
            if not redirect_url.startswith("http"):
                redirect_url = f"https://tiponet.tipo.gov.tw/gpss2/gpsskmc/{redirect_url}"
            res = await client.get(redirect_url)

        # Step 5: Extract detail page and retrieve images
        m_detail = re.search(r'href=["\']?(/gpss[12]/gpsskmc/gpssbkm\?[^\s\'">]+)[^>]*class=["\']?link02["\']?', res.text, re.IGNORECASE)
        if not m_detail:
            print(f"[-] Error: Patent detail link for '{patent_no}' not found in search results.")
            return []
            
        detail_url = f"https://tiponet.tipo.gov.tw{m_detail.group(1)}"
        print(f"[5/5] Fetching patent detail page...")
        res_detail = await client.get(detail_url)
        
        # Extract and de-duplicate figure URLs from detail page
        img_urls = re.findall(r'/gpss[12]/gpssbkmusr/[^\'" >]+', res_detail.text)
        img_urls = [url.split()[0] for url in img_urls]
        img_urls = list(dict.fromkeys(img_urls))
        
        abs_urls = [f"https://tiponet.tipo.gov.tw{url}" for url in img_urls]
        return abs_urls

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 get_gpss_representative_figure.py <patent_number>")
        print("Example: python3 get_gpss_representative_figure.py I854998")
        sys.exit(1)
        
    patent_num = sys.argv[1]
    urls = asyncio.run(get_gpss_figures(patent_num))
    
    if urls:
        print(f"\n[SUCCESS] Extracted {len(urls)} figure URL(s) for patent {patent_num}:")
        for url in urls:
            print(url)
    else:
        print("\n[-] No figures found.")
