﻿#"""
#This file is part of Happypanda.
#Happypanda is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 2 of the License, or
#any later version.
#Happypanda is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#You should have received a copy of the GNU General Public License
#along with Happypanda.  If not, see <http://www.gnu.org/licenses/>.
#"""

import requests, logging, random, time, threading, html, uuid, os
import re as regex
from bs4 import BeautifulSoup
from robobrowser import RoboBrowser
from datetime import datetime
from queue import Queue

from PyQt5.QtCore import QObject, pyqtSignal

import gui_constants

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

class Downloader(QObject):
	"""
	A download manager.
	Emits signal item_finished with tuple of url and path to file when a download finishes
	"""
	_inc_queue = Queue()
	_browser_session = None
	_threads = []
	item_finished = pyqtSignal(tuple)

	def __init__(self):
		super().__init__()
		# download dir
		self.base = os.path.abspath(gui_constants.DOWNLOAD_DIRECTORY)
		if not os.path.exists(self.base):
			os.mkdir(self.base)

	@staticmethod
	def add_to_queue(item, session=None, dir=None):
		"""
		Add an url to the queue or a tuple where first index is name of file.
		An optional requests.Session object can be specified
		A temp dir to be used can be specified
		"""
		if dir:
			Downloader._inc_queue.put({'dir':dir, 'item':item})
		else:
			Downloader._inc_queue.put(item)
		Downloader._session = session

	def _downloading(self):
		"The downloader. Put in a thread."
		while True:
			item = self._inc_queue.get()
			temp_base = None
			if isinstance(item, dict):
				temp_base = item['dir']
				item = item['item']

			file_name = item[0] if isinstance(item, (tuple, list)) else str(uuid.uuid4())
			file_name = os.path.join(self.base, file_name) if not temp_base else \
				os.path.join(temp_base, file_name)
			download_url = item[1] if isinstance(item, (tuple, list)) else item

			if self._browser_session:
				r = self._browser_session.get(download_url, stream=True)
			else:
				r = requests.get(download_url, stream=True)
			with open(file_name, 'wb') as f:
				for data in r.iter_content(chunk_size=1024):
					if data:
						f.write(data)
						f.flush()
			self.item_finished.emit((download_url, file_name))
			self._inc_queue.task_done()

	def start_manager(self, max_tasks):
		"Starts download manager where max simultaneous is mask_tasks"
		for x in range(max_tasks):
			thread = threading.Thread(
					target=self._downloading,
					name='Downloader {}'.format(x),
					daemon=True)
			thread.start()
			self._threads.append(thread)

class HenItem(QObject):
	"A convenience class that most methods in HenManager returns"
	thumb_rdy = pyqtSignal(object)
	file_rdy = pyqtSignal(object)
	def __init__(self, session=None):
		super().__init__()
		self.session = session
		self.thumb_url = "" # an url to gallery thumb
		self.thumb = None
		self.cost = ""
		self.size = ""
		self.name = ""
		self.metadata = None
		self.file = ""
		self.download_url = ""
		self.download_type = gui_constants.HEN_DOWNLOAD_TYPE

	def fetch_thumb(self):
		"Fetches thumbnail. Emits thumb_rdy, when done"
		def thumb_fetched(dl):
			if dl[0] == self.thumb_url:
				self.thumb = dl[1]
				self.thumb_rdy.emit(self)
		gui_constants.DOWNLOAD_MANAGER.item_finished.connect(thumb_fetched)
		Downloader.add_to_queue(self.thumb_url, self.session, gui_constants.temp_dir)

	def _file_fetched(self, dl_data):
		if self.download_url == dl_data[0]:
			self.file = dl_data[1]
			self.file_rdy.emit(self)

class HenManager(QObject):
	"G.e or Ex gallery manager"
	_browser = RoboBrowser(history=True,
						user_agent="Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0",
						parser='html.parser', allow_redirects=False)
	# download type
	ARCHIVE, TORRENT = False, False

	def __init__(self):
		super().__init__()
		self.e_url = 'http://g.e-hentai.org/'
		self.ARCHIVE, self.TORRENT = False, False
		if gui_constants.HEN_DOWNLOAD_TYPE == 0:
			self.ARCHIVE = True
		elif gui_constants.HEN_DOWNLOAD_TYPE == 1:
			self.TORRENT = True

	def _error(self):
		pass

	def _archive_url_d(self, gid, token, key):
		"Returns the archiver download url"
		base = self.e_url + 'archiver.php?'
		d_url = base + 'gid=' + str(gid) + '&token=' + token + '&or=' + key
		return d_url

	def _torrent_url_d(self, gid, token):
		"Returns the torrent download url"
		base = self.e_url + 'gallerytorrents.php?'
		torrent_page = base + 'gid=' + gid + '&t=' + token

		# TODO: get torrents? make user choose?

	def from_gallery_url(self, g_url):
		"""
		Finds gallery download url and puts it in download queue
		"""
		if 'ipb_member_id' in self._browser.session.cookies and \
			'ipb_pass_hash' in self._browser.session.cookies:
			hen = ExHen(self._browser.session.cookies['ipb_member_id'],
			   self._browser.session.cookies['ipb_pass_hash'])
		else:
			hen = EHen()

		api_metadata, gallery_gid_dict = hen.add_to_queue(g_url, True, False)
		gallery = api_metadata['gmetadata'][0]

		h_item = HenItem(self._browser.session)
		h_item.metadata = CommenHen.parse_metadata(api_metadata, gallery_gid_dict)[g_url]
		h_item.thumb_url = gallery['thumb']
		h_item.name = gallery['title']
		h_item.size = "{} MB".format(gallery['filesize'])

		if self.ARCHIVE:
			h_item.download_type = 0
			d_url = self._archive_url_d(gallery['gid'], gallery['token'], gallery['archiver_key'])
			self._browser.open(d_url)
			download_btn = self._browser.get_form()
			if download_btn:
				f_div = self._browser.find('div', id='db')
				divs = f_div.find_all('div')
				h_item.cost = divs[0].find('strong').text
				h_item.size = divs[1].find('strong').text
				self._browser.submit_form(download_btn)
			# get dl link
			dl = self._browser.find('a').get('href')
			self._browser.open(dl)
			succes_test = self._browser.find('p')
			if succes_test and 'successfully' in succes_test.text:
				gallery_dl = self._browser.find('a').get('href')
				gallery_dl = self._browser.url.split('/archive')[0] + gallery_dl
				f_name = succes_test.find('strong').text
				h_item.download_url = gallery_dl
				h_item.fetch_thumb()
				Downloader.add_to_queue((f_name, gallery_dl))
				gui_constants.DOWNLOAD_MANAGER.item_finished.connect(h_item._file_fetched)
				return h_item

		elif self.TORRENT:
			h_item.download_type = 1
			pass
		return False

class ExHenManager(HenManager):
	"ExHentai Manager"
	def __init__(self, ipb_id, ipb_pass):
		super().__init__()
		cookies = {'ipb_member_id':ipb_id,
				  'ipb_pass_hash':ipb_pass}
		self._browser.session.cookies.update(cookies)
		self.e_url = "http://exhentai.org/"



class CommenHen:
	"Contains common methods"
	LOCK = threading.Lock()
	TIME_RAND = gui_constants.GLOBAL_EHEN_TIME
	QUEUE = []
	COOKIES = {}
	LAST_USED = time.time()
	HEADERS = {'user-agent':"Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0"}

	@staticmethod
	def hash_search(g_hash):
		"""
		Searches ex or g.e for a gallery with the hash value
		Return list with titles of galleries found.
		"""
		raise NotImplementedError

	def begin_lock(self):
		log_d('locked')
		self.LOCK.acquire()
		t1 = time.time()
		while int(time.time() - self.LAST_USED) < 4:
			t = random.randint(4, self.TIME_RAND)
			time.sleep(t)
		t2 = time.time() - t1
		log_d("Slept for {}".format(t2))
	
	def end_lock(self):
		log_d('unlocked')
		self.LAST_USED = time.time()
		self.LOCK.release()

	def add_to_queue(self, url, proc=False, parse=True):
		"""Add url the the queue, when the queue has reached 25 entries will auto process
		:proc -> proccess queue
		:parse -> return parsed metadata
		"""
		self.QUEUE.append(url)
		log_i("Status on queue: {}/25".format(len(self.QUEUE)))
		if proc:
			if parse:
				return CommenHen.parse_metadata(*self.process_queue())
			return self.process_queue()
		if len(self.QUEUE) > 24:
			if parse:
				return CommenHen.parse_metadata(*self.process_queue())
			return self.process_queue()
		else:
			return 0

	def process_queue(self):
		"""
		Process the queue if entries exists, deletes entries.
		Note: Will only process 25 entries (first come first out) while
			additional entries will get deleted.
		"""
		log_i("Processing queue...")
		if len(self.QUEUE) < 1:
			return None

		if len(self.QUEUE) > 25:
			api_data, galleryid_dict = self.get_metadata(self.QUEUE[:25])
		else:
			api_data, galleryid_dict = self.get_metadata(self.QUEUE)

		log_i("Flushing queue...")
		self.QUEUE.clear()
		return api_data, galleryid_dict

	def check_cookie(self, cookie):
		assert isinstance(cookie, dict)
		cookies = self.COOKIES.keys()
		present = []
		for c in cookie:
			if c in cookies:
				present.append(True)
			else:
				present.append(False)
		if not all(present):
			log_i("Updating cookies...")
			self.COOKIES.update(cookie)

	def handle_error(self, response):
		content_type = response.headers['content-type']
		text = response.text
		if 'image/gif' in content_type:
			gui_constants.NOTIF_BAR.add_text('Provided exhentai credentials are incorrect!')
			log_e('Provided exhentai credentials are incorrect!')
			time.sleep(5)
			return False
		elif 'text/html' and 'Your IP address has been' in text:
			gui_constants.NOTIF_BAR.add_text("Your IP address has been temporarily banned from g.e-/exhentai")
			log_e('Your IP address has been temp banned from g.e- and ex-hentai')
			time.sleep(5)
			return False
		elif 'text/html' in content_type and 'You are opening' in text:
			time.sleep(random.randint(10,50))
		return True

	@staticmethod
	def parse_url(url):
		"Parses url into a list of gallery id and token"
		gallery_id = int(regex.search('(\d+)(?=\S{4,})', url).group())
		gallery_token = regex.search('(?<=\d/)(\S+)(?=/$)', url).group()
		parsed_url = [gallery_id, gallery_token]
		return parsed_url

	@staticmethod
	def parse_metadata(metadata_json, dict_metadata):
		"""
		:metadata_json -> raw data provided by E-H API
		:dict_metadata -> a dict with galleries as keys and url as value

		returns a dict with url as key and gallery metadata as value
		"""
		def invalid_token_check(g_dict):
			if 'error' in g_dict:
				return False
			else: return True

		parsed_metadata = {}
		for gallery in metadata_json['gmetadata']:
			if invalid_token_check(gallery):
				new_gallery = {}
				def fix_titles(text):
					t = html.unescape(text)
					t = " ".join(t.split())
					return t
				try:
					gallery['title_jpn'] = fix_titles(gallery['title_jpn'])
					gallery['title'] = fix_titles(gallery['title'])
					new_gallery['title'] = {'def':gallery['title'], 'jpn':gallery['title_jpn']}
				except KeyError:
					gallery['title'] = fix_titles(gallery['title'])
					new_gallery['title'] = {'def':gallery['title']}

				new_gallery['type'] = gallery['category']
				new_gallery['pub_date'] = datetime.fromtimestamp(int(gallery['posted']))
				tags = {'default':[]}
				for t in gallery['tags']:
					if ':' in t:
						ns_tag = t.split(':')
						namespace = ns_tag[0].capitalize()
						tag = ns_tag[1].lower()
						if not namespace in tags:
							tags[namespace] = []
						tags[namespace].append(tag)
					else:
						tags['default'].append(t.lower())
				new_gallery['tags'] = tags
				url = dict_metadata[gallery['gid']]
				parsed_metadata[url] = new_gallery
			else:
				log_e("Error in received response with URL: {}".format(url))

		return parsed_metadata

	def get_metadata(self, list_of_urls, cookies=None):
		"""
		Fetches the metadata from the provided list of urls
		through the official API.
		returns raw api data and a dict with gallery id as key and url as value
		"""
		assert isinstance(list_of_urls, list)
		if len(list_of_urls) > 25:
			log_e('More than 25 urls are provided. Aborting.')
			return None

		payload = {"method": "gdata",
			 "gidlist": [],
			 "namespace": 1
			 }
		dict_metadata = {}
		for url in list_of_urls:
			parsed_url = CommenHen.parse_url(url.strip())
			dict_metadata[parsed_url[0]] = url # gallery id
			payload['gidlist'].append(parsed_url)

		if payload['gidlist']:
			self.begin_lock()
			if cookies:
				self.check_cookie(cookies)
				r = requests.post(self.e_url, json=payload, timeout=30, headers=self.HEADERS, cookies=self.COOKIES)
			else:
				r = requests.post(self.e_url, json=payload, timeout=30, headers=self.HEADERS)
			if not self.handle_error(r):
				return 'error'
			self.end_lock()
		else: return None
		try:
			r.raise_for_status()
		except:
			log.exception('Could not fetch metadata: connection error')
			return None
		return r.json(), dict_metadata

	def eh_hash_search(self, hash_string, cookies=None):
		"""
		Searches ehentai for the provided string or list of hashes,
		returns a dict with hash:[list of title,url tuples] of hits found or emtpy dict if no hits are found.
		"""
		assert isinstance(hash_string, (str, list))
		if isinstance(hash_string, str):
			hash_string = [hash_string]

		def no_hits_found_check(html):
			"return true if hits are found"
			soup = BeautifulSoup(html, "html.parser")
			f_div = soup.body.find_all('div')
			for d in f_div:
				if 'No hits found' in d.text:
					return False
			return True

		hash_url = gui_constants.DEFAULT_EHEN_URL + '?f_shash='
		found_galleries = {}
		log_i('Initiating hash search on ehentai')
		for h in hash_string:
			log_d('Hash search: {}'.format(h))
			self.begin_lock()
			if cookies:
				self.check_cookie(cookies)
				r = requests.get(hash_url+h, timeout=30, headers=self.HEADERS, cookies=self.COOKIES)
			else:
				r = requests.get(hash_url+h, timeout=30, headers=self.HEADERS)
			self.end_lock()
			if not self.handle_error(r):
				return 'error'
			if not no_hits_found_check(r.text):
				log_e('No hits found with hash: {}'.format(h))
				continue
			soup = BeautifulSoup(r.text, "html.parser")
			log_i('Parsing html')
			try:
				if soup.body:
					found_galleries[h] = []
					# list view or grid view
					type = soup.find(attrs={'class':'itg'}).name
					if type == 'div':
						visible_galleries = soup.find_all('div', attrs={'class':'id1'})
					elif type == 'table':
						visible_galleries = soup.find_all('div', attrs={'class':'it5'})
				
					log_i('Found {} visible galleries'.format(len(visible_galleries)))
					for gallery in visible_galleries:
						title = gallery.text
						g_url = gallery.a.attrs['href']
						found_galleries[h].append((title,g_url))
			except AttributeError:
				log.exception('Unparseable html')
				log_d("\n{}\n".format(soup.prettify()))
				continue

		if found_galleries:
			log_i('Found {} out of {} galleries'.format(len(found_galleries), len(hash_string)))
			return found_galleries
		else:
			log_w('Could not find any galleries')
			return {}

	def eh_gallery_parser(self, url, cookies=None):
		"""
		Parses an ehentai page for metadata.
		Returns gallery dict with following metadata:
		- title
		- jap_title
		- type
		- language
		- publication date
		- namespace & tags
		"""
		self.begin_lock()
		if cookies:
			self.check_cookie(cookies)
			r = requests.get(url, headers=self.HEADERS, timeout=30, cookies=self.COOKIES)
		else:
			r = requests.get(url, headers=self.HEADERS, timeout=30)
		self.end_lock()
		if not self.handle_error(r):
			return {}
		html = r.text
		if len(html)<5000:
			log_w("Length of HTML response is only {} => Failure".format(len(html)))
			return {}

		gallery = {}
		soup = BeautifulSoup(html)

		#title
		div_gd2 = soup.body.find('div', id='gd2')
		# normal
		title = div_gd2.find('h1', id='gn').text.strip()
		# japanese
		jap_title = div_gd2.find('h1', id='gj').text.strip()

		gallery['title'] = title
		gallery['jap_title'] = jap_title

		# Type
		div_gd3 = soup.body.find('div', id='gd3')
		gallery['type'] = div_gd3.find('img').get('alt')

		# corrects name
		if gallery['type'] == 'artistcg':
			gallery['type'] = 'artist cg sets'
		elif gallery['type'] == 'imageset':
			gallery['type'] = 'image sets'
		elif gallery['type'] == 'gamecg':
			gallery['type'] = 'game cg sets'
		elif gallery['type'] == 'asianporn':
			gallery['type'] = 'asian porn'

		# Language
		lang_tag = soup.find('td', text='Language:').next_sibling
		lang = lang_tag.text.split(' ')[0]
		gallery['language'] = lang

		# Publication date
		pub_tag = soup.find('td', text='Posted:').next_sibling
		pub_date = datetime.strptime(pub_tag.text.split(' ')[0], '%Y-%m-%d').date()
		gallery['published'] = pub_date

		# Namespace & Tags
		found_tags = {}
		def tags_in_ns(tags):
			return not tags.has_attr('class')
		tag_table = soup.find('div', id='taglist').next_element
		namespaces = tag_table.find_all('tr')
		for ns in namespaces:
			namespace = ns.next_element.text.replace(':', '')
			namespace = namespace.capitalize()
			found_tags[namespace] = []
			tags = ns.find(tags_in_ns).find_all('div')
			for tag in tags:
				found_tags[namespace].append(tag.text)

		gallery['tags'] = found_tags
		return gallery

class ExHen(CommenHen):
	"Fetches gallery metadata from exhen"
	def __init__(self, cookie_member_id, cookie_pass_hash):
		self.cookies = {'ipb_member_id':cookie_member_id,
				  'ipb_pass_hash':cookie_pass_hash}
		self.e_url = "http://exhentai.org/api.php"

	def get_metadata(self, list_of_urls):
		return super().get_metadata(list_of_urls, self.cookies)

	def eh_gallery_parser(self, url):
		return super().eh_gallery_parser(url, self.cookies)

	def eh_hash_search(self, hash_string):
		return super().eh_hash_search(hash_string, self.cookies)

class EHen(CommenHen):
	"Fetches galleries from ehen"
	def __init__(self):
		self.e_url = "http://g.e-hentai.org/api.php"

