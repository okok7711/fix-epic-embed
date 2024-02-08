from contextvars import ContextVar

import aiohttp
import fastapi
import ujson
from bs4 import BeautifulSoup
from fastapi.responses import HTMLResponse

_SESSION = ContextVar('SESSION')
app = fastapi.FastAPI()

def generate_og_tag_response_from_info(info: dict, locale: str, slug: str) -> str:
    if not info: 
        info = {
            "url": f"https://store.epicgames.com/{locale}/p/{slug}",
            "locale": locale,
            "title": "",
            "description": "",
            "image": "",
            "color": "#000000"
        }
    return """
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <meta property="og:url" content="{url}"/>
            <meta property="og:site_name" content="Epic Games Store"/>
            <meta property="og:locale" content="{locale}"/>
            <meta property="og:type" content="website"/>
            <meta property="og:title" content="{title}"/>
            <meta property="og:description" content="{description}"/>
            <meta property="og:image" content="{image}"/>
            <meta name="twitter:card" content="summary_large_image"/>
            <meta name="theme-color" content="{color}"/>
        </head>
        <body></body>
    </html>
    """.format(**info)


@app.get("/{locale}/p/{slug}")
async def get_store_info(locale: str, slug: str) -> HTMLResponse:
    GQL_URL = "https://www.epicgames.com/graphql"
    GET_PRODUCT_URL = "https://egs-platform-service.store.epicgames.com/api/v1/egs/products/{product_id}?country=DE&locale={locale}&store=EGS"
    FLARESOLVER_URL = "YOUR_FLARESOLVER_URL"

    async with aiohttp.ClientSession() as session:
        async with session.get(GQL_URL, params={
            "operationName": "getMappingByPageSlug",
            "variables": ujson.dumps({
                "pageSlug": slug,
                "locale": locale
            }),
            "extensions": ujson.dumps({
                "persistedQuery": {"version":1, "sha256Hash":"781fd69ec8116125fa8dc245c0838198cdf5283e31647d08dfa27f45ee8b1f30"}
            })
        }) as response:
            maybe_store_mapping = await response.json()

        if not maybe_store_mapping["data"]["StorePageMapping"].get("mapping"):
            return HTMLResponse(generate_og_tag_response_from_info(None, locale, slug), status_code=404)

        store_mapping = maybe_store_mapping["data"]["StorePageMapping"]["mapping"]

        product_id = store_mapping["productId"]

        async with session.post(
            FLARESOLVER_URL,
            json={
                "cmd": "request.get",
                "url": GET_PRODUCT_URL.format(product_id=product_id, locale=locale),
                "session": "egs",
            }
            ) as response:

            response_data = await response.json()
            soup = BeautifulSoup(response_data['solution']['response'], 'html.parser')
            json_data = soup.find('pre').text
            store_info = ujson.loads(json_data)
        
        image = store_info["media"].get("card16x9")
        if not image:
            image = store_info["media"].get("logo")

        transformed_info = {
            "url": f"https://store.epicgames.com/{locale}/p/{slug}",
            "locale": locale,
            "title": f'{store_info["title"]}',
            "description": store_info["shortDescription"],
            "image": image["imageSrc"],
            "color": store_info["branding"].get("light", {}).get("accentColor", "#000000")
        }

    return HTMLResponse(generate_og_tag_response_from_info(transformed_info, locale, slug))

@app.on_event("startup")
async def startup():
    FLARESOLVER_URL = "YOUR_FLARESOLVER_URL"
    
    _SESSION.set(aiohttp.ClientSession())

    async with _SESSION.get().post(FLARESOLVER_URL, json={
            "cmd": "sessions.create",
            "session": "egs",
        }):
            ...

@app.on_event("shutdown")
async def shutdown():
    FLARESOLVER_URL = "YOUR_FLARESOLVER_URL"

    async with _SESSION.get().post(FLARESOLVER_URL, json={
            "cmd": "sessions.destroy",
            "session": "egs",
        }) as response:
            await response.text()

    await _SESSION.get().close()