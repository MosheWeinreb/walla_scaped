import os
import json
from datetime import datetime
from playwright.async_api import async_playwright, Page, Locator
import asyncio
from typing import Dict, Any
import re
import aiofiles
from tenacity import retry, stop_after_attempt, wait_exponential
import aiohttp


class Config:
    URL = "https://www.kikar.co.il/"
    BASE_URL = "https://www.kikar.co.il"
    HEADLESS = False
    MAX_CONCURRENT_REQUESTS = 5
    JSON_DIR = "json_files"
    IMAGE_DIR = "images"
    SCREENSHOT_DIR = "screenshots"
    IMAGE_SELECTOR = "img.MuiBox-root.css-8fjtk0"
    BUTTON_SELECTOR = (
        ".MuiButtonBase-root.MuiButton-root.MuiButton-text.MuiButton-textPrimary."
        "MuiButton-sizeMedium.MuiButton-textSizeMedium.MuiButton-root.MuiButton-text."
        "MuiButton-textPrimary.MuiButton-sizeMedium.MuiButton-textSizeMedium.css-1mx6moy"
    )
    ARTICLE_CONTENT = ".article-content.MuiBox-root.css-1b737da"
    ARTICLE_DATE_OR_TIME = ".almoni-tzar.MuiBox-root.css-19f8y51"
    ALL_ARTICLE_HREFS = "a.text-decoration-none"


class WebScraper:
    def __init__(self, config):
        self.config = config

    async def main(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.config.HEADLESS)
            context = await browser.new_context()

            async with await context.new_page() as page:
                await page.goto(self.config.URL)
                hrefs_dict = await self.get_all_hrefs(page)
                print(f"Number of articles to process: {len(hrefs_dict)}")

            try:
                hrefs_list = list(hrefs_dict.values())[:5]

                semaphore = asyncio.Semaphore(self.config.MAX_CONCURRENT_REQUESTS)
                tasks = [self.process_article(context, href, index, semaphore)
                         for index, href in enumerate(hrefs_list)]
                results = await asyncio.gather(*tasks)

                for index, article_info in enumerate(results):
                    if article_info:
                        original_id = f"article_{index + 1}"
                        output_path = os.path.join(self.config.JSON_DIR, f"{original_id}.json")
                        await self.save_to_json(article_info, output_path)
                        print(f"Article info saved to {output_path}")
            except Exception as e:
                print(f"Error processing articles: {e}")

            await context.close()

    async def get_href_from_element(self, element, index):
        href = await element.get_attribute("href")

        if href.startswith("https"):
            print(f"link_{index} not an article, probably an ad", href)
        elif href:
            full_href = f"{self.config.BASE_URL}{href}"
            return f"link_{index}", full_href
        return None

    async def get_hrefs_from_elements(self, page):
        elements = await page.query_selector_all(config.ALL_ARTICLE_HREFS)

        href_tasks = [self.get_href_from_element(element, index) for index, element in enumerate(elements)]
        href_results = await asyncio.gather(*href_tasks)

        hrefs_dict = {}
        for result in href_results:
            if result:
                key, value = result
                if value not in hrefs_dict.values():
                    hrefs_dict[key] = value

        return hrefs_dict

    async def get_all_hrefs(self, page):
        all_hrefs = {}
        while True:
            current_hrefs = await self.get_hrefs_from_elements(page)
            all_hrefs.update(current_hrefs)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            end_of_page = await page.evaluate(
                "(window.innerHeight + window.scrollY) >= document.body.offsetHeight")
            if end_of_page:
                break
        return all_hrefs

    async def get_author_info(self, page):
        try:
            author_element = await page.query_selector(Config.ARTICLE_CONTENT)
            author_href = await author_element.get_attribute("href")
            author_text = await author_element.inner_text()
            author = {"text": author_text, "href": f"{self.config.BASE_URL}{author_href}"}
            return author
        except Exception:
            return {"text": "Could not get author", "href": ""}

    async def get_time_or_date_published(self, page):
        try:
            parent_element = await page.wait_for_selector(config.ARTICLE_DATE_OR_TIME)
            full_text = await parent_element.inner_text()
            time_pattern = r"\d{1,2}:\d{2}"
            date_pattern = r"(\d{1,2}\.\d{2}\.\d{2})"
            time_match = re.search(time_pattern, full_text)
            date_match = re.search(date_pattern, full_text)
            if time_match:
                time_str = time_match.group(0).strip()
                today_date = datetime.now().strftime("%d/%m/%Y")
                return f"{today_date} {time_str}"
            elif date_match:
                date_str = date_match.group(1).strip()
                return date_str
            else:
                print("Neither time nor date found in the text")
                return None
        except Exception as e:
            print(f"Error getting time or date published: {e}")
            return None

    async def get_article_content(self, page):
        try:
            await page.wait_for_selector(
                config.ARTICLE_CONTENT, timeout=5000
            )
            main_content_element = await page.query_selector(
                config.ARTICLE_CONTENT
            )
            content = await main_content_element.inner_text()
            if content:
                content = content.replace("\\", "")
                content = content.replace('"', "")
                content = content.replace("\n", "")
            return content.strip()
        except Exception as e:
            print(f"Error getting article content: {e}")
            return None

    async def get_image_info(self, page: Page, article_id: str):
        try:
            image_elements: list[Locator] = await page.locator(self.config.IMAGE_SELECTOR).all()
            image_sources_tasks = [element.get_attribute('src') for element in image_elements]
            image_sources = await asyncio.gather(*image_sources_tasks)

            image_info_list = []
            for idx, src in enumerate(image_sources):
                if src:
                    img_id = f"{article_id}_image_{idx}"
                    img_path = os.path.join(self.config.IMAGE_DIR, f"{img_id}.jpg")
                    image_info_list.append({"id": img_id, "src": src, "path": img_path})
                    await self.download_image(src, img_path)
            return image_info_list
        except Exception as e:
            print(f"Error getting image info: {e}")
            return []

    async def download_image(self, src, file_path):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(src) as response:
                    if response.status == 200:
                        content = await response.read()
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        async with aiofiles.open(file_path, "wb") as f:
                            await f.write(content)

        except Exception as e:
            print(f"Error downloading image {src}: {e}")

    async def take_screenshot(self, page: Page, article_id: str):
        try:
            screenshot_path = os.path.join(self.config.SCREENSHOT_DIR, f"{article_id}_screenshot.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            return screenshot_path
        except Exception as e:
            print(f"Error taking screenshot: {e}")
            return None

    @retry(stop=stop_after_attempt(1), wait=wait_exponential(multiplier=1, min=4, max=6))
    async def visit_article_and_get_info(self, page, href, index):
        article_info = {}
        try:
            await page.goto(href)
            await page.wait_for_selector(self.config.BUTTON_SELECTOR, timeout=5000)
            scraped_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            headline = await page.inner_text("h1")
            author = await self.get_author_info(page)
            time_published = await self.get_time_or_date_published(page)
            content = await self.get_article_content(page)
            images = await self.get_image_info(page, f"article_{index}")
            screenshots = await self.take_screenshot(page, f"article_{index}")

            article_info = {
                "scraped_time": scraped_time,
                "headline": headline,
                "url": href,
                "author": author,
                "time_published": time_published,
                "content": content,
                "images": images,
                "screenshots": screenshots,
            }
        except Exception as e:
            print(f"Error visiting article {href}: {e}")
        return article_info

    async def process_article(self, context, href, index, semaphore):
        async with semaphore:
            async with await context.new_page() as page:
                try:
                    article_info = await self.visit_article_and_get_info(page, href, index)
                    if article_info:
                        return article_info
                except Exception as e:
                    print(f"Error processing article {href}: {e}")
                    return None

    async def save_to_json(self, data, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        try:
            async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=4))
        except Exception as e:
            print(f"Error saving data to JSON file {output_path}: {e}")


if __name__ == "__main__":
    config = Config()
    scraper = WebScraper(config)
    asyncio.run(scraper.main())