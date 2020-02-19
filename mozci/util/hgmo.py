import requests
from adr.util.memoize import memoize


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
        if self.branch == 'autoland':
            self.branch_slug = 'integration/autoland'
        else:
            self.branch_slug = self.branch

    @staticmethod
    def create(rev, branch='autoland'):
        key = (branch, rev)
        if key in HGMO.CACHE:
            return HGMO.CACHE[key]
        instance = HGMO(rev, branch)
        HGMO.CACHE[key] = instance
        return instance

    @memoize
    def _get_resource(self, field, **kwargs):
        kwargs.update({'rev': self.rev, 'branch': self.branch_slug})
        url = getattr(HGMO, field.upper() + "_TEMPLATE").format(**kwargs)

        r = requests.get(url)
        r.raise_for_status()
        return r.json()

    @property
    def automation_relevance(self):
        return self._get_resource('automation_relevance')['changesets'][0]

    @property
    def data(self):
        return self._get_resource('json')

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
        return self._get_resource('json_pushes', push_id_start, push_id_end)['pushes']

    @property
    def is_backout(self):
        return len(self.automation_relevance['backsoutnodes']) > 0
