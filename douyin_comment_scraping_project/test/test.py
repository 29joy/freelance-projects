# test_douyin_comments.py
from playwright.sync_api import sync_playwright
import time

def test_douyin_comment(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(url)
        time.sleep(5)  # 等页面加载
        try:
            # 尝试点击评论按钮（若存在）
            comment_button = page.locator('xpath=//span[contains(text(), "评论")]')
            if comment_button.count() > 0:
                comment_button.first.click()
                time.sleep(3)
            
            # 抓取评论内容
            comments = page.locator('xpath=//div[contains(@class, "comment-item")]')
            count = comments.count()
            print(f"Found {count} comment items on the page.")
            
            # 打印前几个评论文字
            for i in range(min(5, count)):
                text = comments.nth(i).inner_text()
                print(f"Comment {i+1}: {text[:80]}")
        except Exception as e:
            print("Error:", e)
        finally:
            browser.close()

# 示例链接
test_douyin_comment("https://www.iesdouyin.com/share/video/6829473509677366531/")
