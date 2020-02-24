from adr.util.memoize import memoize

from mozci.util.req import get_session


class HGMO():
    # urls
    BASE_URL = "https://hg.mozilla.org/"
    AUTOMATION_RELEVANCE_TEMPLATE = BASE_URL + "{branch}/json-automationrelevance/{rev}"
    JSON_TEMPLATE = BASE_URL + "{branch}/rev/{rev}?style=json"
    JSON_PUSHES_TEMPLATE = BASE_URL + "{branch}/json-pushes?version=2&startID={push_id_start}&endID={push_id_end}"  # noqa

    # instance cache
    CACHE = {}

    def __init__(self, rev, branch='autoland'):
        self.rev = rev
        self.branch = branch

        self.context = {
            'branch': 'integration/autoland' if self.branch == 'autoland' else self.branch,
            'rev': self.rev,
        }

    @staticmethod
    def create(rev, branch='autoland'):
        key = (branch, rev)
        if key in HGMO.CACHE:
            return HGMO.CACHE[key]
        instance = HGMO(rev, branch)
        HGMO.CACHE[key] = instance
        return instance

    @memoize
    def _get_resource(self, url):
        r = get_session("hgmo").get(url)
        r.raise_for_status()
        return r.json()

    @property
    def automation_relevance(self):
        url = self.AUTOMATION_RELEVANCE_TEMPLATE.format(**self.context)
        return self._get_resource(url)['changesets'][0]

    @property
    def data(self):
        url = self.JSON_TEMPLATE.format(**self.context)
        return self._get_resource(url)

    def __getitem__(self, k):
        try:
            return self.data[k]
        except KeyError:
            return self.automation_relevance[k]

    def get(self, k, default=None):
        try:
            return self[k]
        except KeyError:
            return default

    def json_pushes(self, push_id_start, push_id_end):
        url = self.JSON_PUSHES_TEMPLATE.format(
            push_id_start=push_id_start,
            push_id_end=push_id_end,
            **self.context,
        )
        return self._get_resource(url)['pushes']

    @property
    def is_backout(self):
        return len(self.automation_relevance['backsoutnodes']) > 0
