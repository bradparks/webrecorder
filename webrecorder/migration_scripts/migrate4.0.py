import sys
import os
import datetime

# add parent dir to path to access webrecorder package
wr_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, wr_path)


from redis import StrictRedis
from fakeredis import FakeStrictRedis
import fakeredis

import json
import shutil

from pywb.utils.loaders import BlockLoader

from webrecorder.rec.storage.storagepaths import add_local_store_prefix

from webrecorder.models import User, Collection, Recording, BookmarkList
from webrecorder.models.usermanager import CLIUserManager, UserTable

from webrecorder.utils import sanitize_title


# ============================================================================
class Migration(object):
    def __init__(self, old_redis_url, new_redis_url, dry_run=True):
        self.old_redis = StrictRedis.from_url(old_redis_url, decode_responses=True)
        self.dry_run = dry_run
        self.per_recording_list = False

        print('DRY RUN', self.dry_run)
        if self.dry_run:
            import redis
            redis.StrictRedis = fakeredis.FakeStrictRedis
            self.redis = FakeStrictRedis.from_url(new_redis_url, decode_responses=True)
        else:
            self.redis = StrictRedis.from_url(new_redis_url, decode_responses=True)

        print('Redis Inited')

        self.cli = CLIUserManager(new_redis_url)

    def delete_user(self, username):
        user = self.cli.all_users.get_user(username)
        user.delete_me()

    def delete_coll(self, username, coll_name):
        print('Deleting Collection: {0}/{1}'.format(username, coll_name))
        user = self.cli.all_users.get_user(username)
        if not user:
            print('No User')
            return

        collection = user.get_collection_by_name(coll_name)
        if not collection:
            print('No Collection')
            return

        user.remove_collection(collection)

    def migrate_all(self):
        all_users = self.old_redis.hkeys('h:users')
        print('NUM USERS:', len(all_users))
        for user in all_users:
            self.migrate_user(user)

    def migrate_user(self, username, new_username=None, coll_name=None, skip_if_exists=True):
        new_username = new_username or username
        print('Processing User: {0} -> {1}'.format(username, new_username))

        if new_username not in self.cli.all_users:
            # migrate from h:users and u:<info> to new user info
            user_data = self.old_redis.hget('h:users', username)
            user_data = json.loads(user_data)
            reg_data = user_data.pop('desc', '')
            if reg_data:
                user_data['reg_data'] = reg_data

            user_data.pop('space_utilization', '')

            # update with u:<id:info data
            old_u_key = User.INFO_KEY.format(user=username)
            user_data.update(self.old_redis.hgetall(old_u_key))

            # update new username with data
            new_u_key = User.INFO_KEY.format(user=new_username)
            self.redis.hmset(new_u_key, user_data)

            # add user to s:users, now a valid user!
            self.redis.sadd(UserTable.USERS_KEY, new_username)
        else:
            if skip_if_exists:
                print('User exists, skipping')
                return

            print('Use already exists, migrating collections')

        user = self.cli.all_users.get_user(new_username)

        if not coll_name:
            # get all collection list
            colls = self.old_redis.smembers(User.COLLS_KEY.format(user=new_username))
        else:
            colls = [coll_name]

        for coll in colls:
            print('  Processing Collection: ' + coll)
            self.migrate_collection(user, username, coll)

        try:
            target_dirname = user.get_user_temp_warc_path()
            os.rmdir(target_dirname)
        except Exception as e:
            print('Error deleting user dir: ' + str(e))


    def migrate_collection(self, user, old_user, old_coll):
        # get old coll info data
        old_info_key = 'c:{user}:{coll}:info'.format(user=old_user, coll=old_coll)
        old_coll_data = self.old_redis.hgetall(old_info_key)

        if not old_coll_data or not old_coll_data.get('id'):
            print('  SKIPPING INVALID: ' + old_coll)
            return

        collection = user.create_collection(old_coll,
                                            allow_dupe=False,
                                            title=old_coll_data.get('title', ''),
                                            desc=old_coll_data.get('desc', ''),
                                            public=old_coll_data.get('r:@public') == '1')

        print('  New Collection Created: ' + collection.my_id)

        if old_coll_data.get('created_at'):
            collection.set_prop('created_at', old_coll_data.get('created_at'))
        else:
            print('  OBJ ERR: created_at missing')

        collection.set_prop('size', old_coll_data.get('size', '0'))

        collection.bookmarks_list = None

        recs = self.old_redis.smembers('c:{user}:{coll}:recs'.format(user=old_user, coll=old_coll))

        patch_recordings = {}

        for rec in recs:
            old_rec_base_key = 'r:{user}:{coll}:{rec}:'.format(user=old_user, coll=old_coll, rec=rec)
            print('    Processing Recording: ' + rec)
            recording = self.migrate_recording(collection, rec, old_rec_base_key)

            # track patch recordings
            if recording and recording.get_prop('rec_type') == 'patch':
                print('    Patch: yes')
                id_ = self.old_redis.hget(old_rec_base_key + 'info', 'id')
                patch_recordings[id_] = recording

        # map source to patch recordings, if any
        if not patch_recordings:
            return

        all_recordings = collection.get_recordings()
        for recording in all_recordings:
            title = recording.get_prop('title')
            if not title:
                continue

            patch_title = 'patch-of-' + sanitize_title(title)
            patch_recording = patch_recordings.get(patch_title)
            if patch_recording:
                print('Patch Mapped ({0}) {1} -> {2}'.format(title, recording.my_id, patch_recording.my_id))
                recording.set_patch_recording(patch_recording)

    def migrate_recording(self, collection, rec, old_rec_base_key):
        # old rec info
        old_rec_data = self.old_redis.hgetall(old_rec_base_key + 'info')

        if not old_rec_data or not old_rec_data.get('id'):
            print('SKIPPING INVALID: ' + rec)
            return

        # get remote archive list
        ra_list = self.old_redis.smembers(old_rec_base_key + 'ra')

        # set title
        title = old_rec_data.get('title', rec)
        rec_type = old_rec_data.get('rec_type')

        recording = collection.create_recording(title=title,
                                                desc='',
                                                rec_type=rec_type,
                                                ra_list=ra_list)

        print('    New Recording Created: ' + recording.my_id)

        # copy props
        if 'created_at' in old_rec_data:
            recording.set_prop('created_at', old_rec_data['created_at'])
        else:
            print('    OBJ ERR: created_at missing')

        if 'updated_at' in old_rec_data:
            recording.set_prop('updated_at', old_rec_data['updated_at'])
            recording.set_prop('recorded_at', old_rec_data['updated_at'])
        else:
            print('    OBJ ERR: updated_at missing')

        pages = self.old_redis.hvals(old_rec_base_key + 'page')
        pages = [json.loads(page) for page in pages]
        collection.import_pages(pages, recording)

        # copy files
        warc_files = self.old_redis.hgetall(old_rec_base_key + 'warc')

        self.copy_rec_files(collection.get_owner(), collection, recording, warc_files)

        # and list for public pages
        visible_pages = [page for page in pages if page.get('hidden') != '1']

        if not visible_pages:
            return recording

        # shared 'Bookmarks' list
        if not collection.bookmarks_list:
            public_desc = 'List automatically created from visible pages on ' + self.datestring()

            collection.bookmarks_list = collection.create_bookmark_list(dict(title='Bookmarks',
                                                                             desc=public_desc,
                                                                             public=True))
        # per-recording list of public bookmarks
        if self.per_recording_list:
            recording_list = collection.create_bookmark_list(dict(title=title,
                                                                  public=False))
        else:
            recording_list = None

        # create bookmarks for visible pages
        for page in visible_pages:
            #page['rec'] = recording.my_id
            page['page_id'] = collection._new_page_id(page)

            print('    BOOKMARK: ' + page.get('timestamp', '') + ' ' + page.get('url', ''))

            if recording_list:
                bookmark_1 = recording_list.create_bookmark(page)
            bookmark_2 = collection.bookmarks_list.create_bookmark(page)

        return recording

    def copy_rec_files(self, user, collection, recording, warc_files):
        if self.dry_run:
            target_dirname = os.path.join('/tmp/migrate4.0', collection.my_id)
        else:
            target_dirname = user.get_user_temp_warc_path()

        os.makedirs(target_dirname, exist_ok=True)
        print('Writing to dir: ' + target_dirname)

        coll_warc_key = recording.COLL_WARC_KEY.format(coll=collection.my_id)
        rec_warc_key = recording.REC_WARC_KEY.format(rec=recording.my_id)

        # Copy WARCs
        loader = BlockLoader()

        for n, url in warc_files.items():
            if not url.startswith('s3://'):
                print('FILE ERR: Skipping local file: ' + url)
                continue

            local_filename = n if n != recording.INDEX_FILE_KEY else os.path.basename(url)
            target_file = os.path.join(target_dirname, local_filename)

            src = loader.load(url)

            try:
                with open(target_file, 'wb') as dest:
                    print('Copying {0} -> {1}'.format(url, target_file))
                    shutil.copyfileobj(src, dest)
                    size = dest.tell()

                target_file = add_local_store_prefix(target_file)
                if n != recording.INDEX_FILE_KEY:
                    self.redis.hset(coll_warc_key, n, target_file)
                    self.redis.sadd(rec_warc_key, n)
                else:
                    recording.set_prop(n, target_file)

                if self.dry_run:
                    os.remove(target_file)

            except:
                import traceback
                traceback.print_exc()

        # commit from temp dir to storage
        if not self.dry_run:
            recording.commit_to_storage()

    def datestring(self):
        return datetime.datetime.utcnow().isoformat()[:19].replace('T', ' ')


# ============================================================================
def main(overwrite=False):
    m = Migration(old_redis_url=os.environ['REDIS_MIGRATE_URL'],
                  new_redis_url=os.environ.get('NEW_REDIS_URL', 'redis://redis:6379/1'),
                  dry_run=False)

    if overwrite:
        m.delete_coll(sys.argv[1], sys.argv[2])

    #if sys.argv[1] == '*':
    m.migrate_all()

    #m.migrate_user(username=sys.argv[1],
    #               coll_name=sys.argv[2])


# ============================================================================
if __name__ == '__main__':
    main()

