import re



# print(book.parodies)

twitter_url = re.search(r"https?://(?:x|twitter)\.com/([^/]+)/status/(\d+)", message.content)

fixed_link = re.sub(
    r"https?://(?:x\.com|twitter\.com)",
    lambda m: "https://fixupx.com" if 1 else (
        "https://g.fixupx.com" if "x.com" in m.group(0) else "https://g.fxtwitter.com"
    ),
    twitter_url.group(0)
)

print 