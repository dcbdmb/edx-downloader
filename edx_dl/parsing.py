# -*- coding: utf-8 -*-

"""
Parsing and extraction functions
"""
import re

from bs4 import BeautifulSoup as BeautifulSoup_

from datetime import timedelta, datetime
from .common import Course, Section, SubSection, Unit

# Force use of bs4 with html5lib
BeautifulSoup = lambda page: BeautifulSoup_(page, 'html5lib')

def edx_json2srt(o):
    """
    Transform the dict 'o' into the srt subtitles format
    """
    BASE_TIME = datetime(1, 1, 1)
    output = []

    for i, (s, e, t) in enumerate(zip(o['start'], o['end'], o['text'])):
        if t == '':
            continue

        output.append(str(i) + '\n')

        s = BASE_TIME + timedelta(seconds=s/1000.)
        e = BASE_TIME + timedelta(seconds=e/1000.)
        time_range = "%02d:%02d:%02d,%03d --> %02d:%02d:%02d,%03d\n" % \
                     (s.hour, s.minute, s.second, s.microsecond/1000,
                      e.hour, e.minute, e.second, e.microsecond/1000)

        output.append(time_range)
        output.append(t + "\n\n")

    return ''.join(output)


class PageExtractor(object):
    """
    Base class for PageExtractor
    Every subclass should implement the extract_units_from_html method.

    Usage:

      >>> import parsing
      >>> d = parsing.SubclassFromPageExtractor()
      >>> units = d.extract_units_from_html(page, BASE_URL)
    """

    def extract_units_from_html(self, page, BASE_URL):
        """
        Method to extract the resources (units) from the given page
        """
        raise NotImplementedError("Subclasses should implement this")


class ClassicEdXPageExtractor(PageExtractor):

    def extract_units_from_html(self, page, BASE_URL):
        """
        Extract Units from the html of a subsection webpage as a list of resources
        """
        # in this function we avoid using beautifulsoup for performance reasons
        # parsing html with regular expressions is really nasty, don't do this if
        # you don't need to !
        re_units = re.compile('(<div?[^>]id="seq_contents_\d+".*?>.*?<\/div>)', re.DOTALL)
        units = []
        for unit_html in re_units.findall(page):
            unit = self.extract_unit(unit_html, BASE_URL)
            if unit is not None and (unit.video_youtube_url is not None or len(unit.mp4_urls) > 0 or len(unit.resources_urls) > 0):
                units.append(unit)
        return units

    def extract_unit(self, text, BASE_URL):
        """
        Parses the <div> of each unit and extracts the urls of its resources
        """
        video_youtube_url = self.extract_video_youtube_url(text)
        available_subs_url, sub_template_url = self.extract_subtitle_urls(text, BASE_URL)
        mp4_urls = self.extract_mp4_urls(text)
        resources_urls = self.extract_resources_urls(text, BASE_URL)
        unit = Unit(video_youtube_url=video_youtube_url,
                    available_subs_url=available_subs_url,
                    sub_template_url=sub_template_url,
                    mp4_urls=mp4_urls,
                    resources_urls=resources_urls)
        return unit

    def extract_video_youtube_url(self, text):
        re_video_youtube_url = re.compile(r'data-streams=&#34;.*?1.0\d+\:(?:.*?)(.{11})')
        video_youtube_url = None
        match_video_youtube_url = re_video_youtube_url.search(text)
        if match_video_youtube_url is not None:
            video_id = match_video_youtube_url.group(1)
            video_youtube_url = 'https://youtube.com/watch?v=' + video_id
        return video_youtube_url

    def extract_subtitle_urls(self, text, BASE_URL):
        re_sub_template_url = re.compile(r'data-transcript-translation-url=(?:&#34;|")([^"&]*)(?:&#34;|")')
        re_available_subs_url = re.compile(r'data-transcript-available-translations-url=(?:&#34;|")([^"&]*)(?:&#34;|")')
        available_subs_url = None
        sub_template_url = None
        match_subs = re_sub_template_url.search(text)
        if match_subs:
            match_available_subs = re_available_subs_url.search(text)
            if match_available_subs:
                available_subs_url = BASE_URL + match_available_subs.group(1)
                sub_template_url = BASE_URL + match_subs.group(1) + "/%s"
        return available_subs_url, sub_template_url

    def extract_mp4_urls(self, text):
        # mp4 urls may be in two places, in the field data-sources, and as <a> refs
        # This regex tries to match all the appearances, however we exclude the ';'
        # character in the urls, since it is used to separate multiple urls in one
        # string, however ';' is a valid url name character, but it is not really
        # common.
        re_mp4_urls = re.compile(r'(?:(https?://[^;]*?\.mp4))')
        mp4_urls = list(set(re_mp4_urls.findall(text)))
        return mp4_urls

    def extract_resources_urls(self, text, BASE_URL):
        re_resources_urls = re.compile(r'href=(?:&#34;|")([^"&]*pdf)')
        resources_urls = [url
                          if url.startswith('http') or url.startswith('https')
                          else BASE_URL + url
                          for url in re_resources_urls.findall(text)]
        return resources_urls


import json
from six.moves import html_parser

class NewEdXPageExtractor(ClassicEdXPageExtractor):
    """
    A new page extractor for the recent changes in layout of edx
    """
    def extract_unit(self, text, BASE_URL):
        re_metadata = re.compile(r'data-metadata=&#39;(.*?)&#39;')
        match_metadata = re_metadata.findall(text)
        if match_metadata:
            metadata = json.loads(html_parser.HTMLParser().unescape(match_metadata[0]))

            video_youtube_url = None
            re_video_speed = re.compile(r'1.0\d+\:(?:.*?)(.{11})')
            match_video_youtube_url = re_video_speed.search(metadata['streams'])
            if match_video_youtube_url is not None:
                video_id = match_video_youtube_url.group(1)
                video_youtube_url = 'https://youtube.com/watch?v=' + video_id

            # notice that the concrete languages come now in
            # so we can eventually build the full urls here
            # subtitles_download_urls = {sub_lang:
            #                            BASE_URL + metadata['transcriptTranslationUrl'].replace('__lang__', sub_lang)
            #                            for sub_lang in metadata['transcriptLanguages'].keys()}
            available_subs_url = BASE_URL + metadata['transcriptAvailableTranslationsUrl']
            sub_template_url = BASE_URL + metadata['transcriptTranslationUrl'].replace('__lang__', '%s')

            # notice that the urls for video downloads come also here, but we
            # prefer to extract them with the old method to match the case of
            # videos who are referenced as links
            # mp4_urls = [url for url in metadata['sources'] if url.endswith('.mp4')]
            mp4_urls = self.extract_mp4_urls(text)
            resources_urls = self.extract_resources_urls(text, BASE_URL)
            unit = Unit(video_youtube_url=video_youtube_url,
                        available_subs_url=available_subs_url,
                        sub_template_url=sub_template_url,
                        mp4_urls=mp4_urls,
                        resources_urls=resources_urls)
            return unit
        return None


def get_page_extractor(url):
    """
    factory method for page extractors
    """
    if url.startswith('https://courses.edx.org'):
        return NewEdXPageExtractor()
    return ClassicEdXPageExtractor()


def extract_courses_from_html(page, BASE_URL):
    """
    Extracts courses (Course) from the html page
    """
    soup = BeautifulSoup(page)
    courses_soup = soup.find_all('article', 'course')
    courses = []
    for course_soup in courses_soup:
        course_id = None
        course_name = course_soup.h3.text.strip()
        course_url = None
        course_state = 'Not yet'
        try:
            # started courses include the course link in the href attribute
            course_url = BASE_URL + course_soup.a['href']
            if course_url.endswith('info') or course_url.endswith('info/'):
                course_state = 'Started'
            # The id of a course in edX is composed by the path
            # {organization}/{course_number}/{course_run]
            course_id = course_soup.a['href'][9:-5]
        except KeyError:
            pass
        courses.append(Course(id=course_id,
                              name=course_name,
                              url=course_url,
                              state=course_state))
    return courses


def extract_sections_from_html(page, BASE_URL):
    """
    Extract sections (Section->SubSection) from the html page
    """
    def _make_url(section_soup):  # FIXME: Extract from here and test
        return BASE_URL + section_soup.ul.find('a')['href']

    def _get_section_name(section_soup):  # FIXME: Extract from here and test
        return section_soup.h3.a.string.strip()

    def _make_subsections(section_soup):
        subsections_soup = section_soup.ul.find_all("li")
        # FIXME correct extraction of subsection.name (unicode)
        subsections = [SubSection(position=i,
                                  url=BASE_URL + s.a['href'],
                                  name=s.p.string)
                       for i, s in enumerate(subsections_soup, 1)]
        return subsections

    soup = BeautifulSoup(page)
    sections_soup = soup.find_all('div', attrs={'class': 'chapter'})

    sections = [Section(position=i,
                        name=_get_section_name(section_soup),
                        url=_make_url(section_soup),
                        subsections=_make_subsections(section_soup))
                for i, section_soup in enumerate(sections_soup, 1)]
    return sections
