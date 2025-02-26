from bs4 import BeautifulSoup as _soup
from urllib.parse import quote
import requests, json

from . import errors

SEARCH_URL = "http://nhentai.net/search?q={}&page={}"
IMAGE_URL = "https://i.nhentai.net/galleries/{}/{}"
DOUJIN_URL = "https://nhentai.net/g/{}"

session = requests.Session()

class Doujinshi():
	"""
	.name = primary/english name
	.jname = secondary/non english name
	.tags = a list of numerical tags
	.magic = magic number/id
	.cover = cover(thumbnail)
	.gid = /galleries/ id for page lookup
	.pages = number of pages
	"""
	def __init__(self, arg):
		self._images = []
		self.fetched = False
		if type(arg) is int:
			self.init_from_id(arg)
		else:
			self.init_from_div(arg)

	def init_from_div(self, res):
		if res.div and res.a:
			self.name = res.div.text
			self.magic = int(res.a['href'][3:-1:])
			self._set_cover(res)
		else:
			raise ValueError("Invalid div structure")
			
	def init_from_id(self, magic):
		res = _get(DOUJIN_URL.format(magic))
		if res.find(class_='container error'):
			raise errors.DoujinshiNotFound()

		self.magic = magic
		cover_res = res.find(id='cover')
		if cover_res:
			self._set_cover(cover_res)
		else:
			raise ValueError("Cover not found")

		info_res = res.find(id='info')
		if info_res and info_res.h1:
			self.name = info_res.h1.text
		else:
			raise ValueError("Info or title not found")

		self.fetch(res)  # since res was already requested
		
	def _set_cover(self, res):
		try:
			self.cover = res.img['data-src']
		except:
			self.cover = 'https:' + res.img['src']
		self.gid = int(self.cover.rsplit('/', 2)[-2])
	
	def fetch(self, res=None):
		if not res:
			res = _get(DOUJIN_URL.format(self.magic))
		# add pages
		for thumb in res.find_all(class_='gallerythumb'):
			img = thumb.find('noscript').img if thumb.find('noscript') else None
			if img:
				url = img['src'].rsplit('/', 1)[-1]
				self._images.append(IMAGE_URL.format(self.gid, url.replace('t', '')))
			else:
				print("Image not found for a gallerythumb")
		# set info (jname, pages, tags)
		info_res = res.find(id='info')
		if info_res:
			self.jname = info_res.h2.text if info_res.h2 else None
			self.pages = len(self._images)

			self.parodies = ""
			self.characters = ""
			self.tags = ""
			self.artists = ""
			self.groups = ""
			self.languages = ""

			self.wewo = 0

			for sub_tag in res('div', class_='tag-container'):
			# for tag in res('a', class_='tag'):
				for a in sub_tag('a', class_='tag'):
					for span in a('span', class_='name'):
						if "Parodies" in sub_tag.text:
							text_parts = span.text.split(' ')
							url_part = '-'.join(text_parts[:-1]) if len(text_parts) > 1 else text_parts[0]
							self.parodies += f'[{span.text}](https://nhentai.net/parody/{url_part}), '
						if "Characters" in sub_tag.text:
							text_parts = span.text.split(' ')
							url_part = '-'.join(text_parts[:-1]) if len(text_parts) > 1 else text_parts[0]
							self.characters += f'[{span.text}](https://nhentai.net/character/{url_part}), '
						if "Tags" in sub_tag.text:
							if "lolicon" in a.text:
								self.wewo = 1
							self.tags += span.text + ', '
						if "Artists" in sub_tag.text:
							text_parts = span.text.split(' ')
							url_part = '-'.join(text_parts[:-1]) if len(text_parts) > 1 else text_parts[0]
							self.artists += f'[{span.text}](https://nhentai.net/artist/{url_part}), '
						if "Groups" in sub_tag.text:
							text_parts = span.text.split(' ')
							url_part = '-'.join(text_parts[:-1]) if len(text_parts) > 1 else text_parts[0]
							self.groups += f'[{span.text}](https://nhentai.net/group/{url_part}), '
						if "Languages" in sub_tag.text:
							self.languages += span.text + ', '

			self.fetched = True
		else:
			raise ValueError("Info section not found")
		
	def __getitem__(self, key):
		if not self.fetched:
			self.fetch()
		return self._images[key]
		
	def __getattr__(self, key):
		if key in {'jname', 'pages', 'tags'}:
			self.fetch()
			if hasattr(self, key):
				return getattr(self, key)
		raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")
		
	def __repr__(self):
		return 'doujin:' + str(self.magic)
		
def _get(endpoint: str):
    response = session.get(endpoint)
    if response.status_code != 200:
        raise ValueError(f"Failed to retrieve content from {endpoint}")
    return _soup(response.text, 'lxml')
	
def search(query:str, page:int=1):
	res = _get(SEARCH_URL.format(quote(query), page))
	for div in res(class_='gallery'):
		yield Doujinshi(div)