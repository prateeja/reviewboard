# coding: utf-8
from __future__ import unicode_literals

import struct
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.utils import six
from djblets.siteconfig.models import SiteConfiguration
from djblets.testing.decorators import add_fixtures

from reviewboard.extensions.tests import TestService
from reviewboard.hostingsvcs.service import (register_hosting_service,
                                             unregister_hosting_service)
from reviewboard.hostingsvcs.models import HostingServiceAccount
from reviewboard.reviews.detail import InitialStatusUpdatesEntry, ReviewEntry
from reviewboard.reviews.models import (Comment,
                                        GeneralComment,
                                        Review)
from reviewboard.site.urlresolvers import local_site_reverse
from reviewboard.testing import TestCase


class ViewTests(TestCase):
    """Tests for views in reviewboard.reviews.views."""

    fixtures = ['test_users', 'test_scmtools', 'test_site']

    def setUp(self):
        super(ViewTests, self).setUp()

        self.siteconfig = SiteConfiguration.objects.get_current()
        self.siteconfig.set('auth_require_sitewide_login', False)
        self.siteconfig.save()

    def test_review_detail_redirect_no_slash(self):
        """Testing review_detail view redirecting with no trailing slash"""
        response = self.client.get('/r/1')
        self.assertEqual(response.status_code, 301)

    def test_review_detail(self):
        """Testing review_detail view"""
        review_request = self.create_review_request(publish=True)

        response = self.client.get('/r/%d/' % review_request.id)
        self.assertEqual(response.status_code, 200)

        request = self._get_context_var(response, 'review_request')
        self.assertEqual(request.pk, review_request.pk)

    def test_review_detail_context(self):
        """Testing review_detail view's context"""
        # Make sure this request is made while logged in, to catch the
        # login-only pieces of the review_detail view.
        self.client.login(username='admin', password='admin')

        username = 'admin'
        summary = 'This is a test summary'
        description = 'This is my description'
        testing_done = 'Some testing'

        review_request = self.create_review_request(
            publish=True,
            submitter=username,
            summary=summary,
            description=description,
            testing_done=testing_done)

        response = self.client.get('/r/%s/' % review_request.pk)
        self.assertEqual(response.status_code, 200)

        request = self._get_context_var(response, 'review_request')
        self.assertEqual(request.submitter.username, username)
        self.assertEqual(request.summary, summary)
        self.assertEqual(request.description, description)
        self.assertEqual(request.testing_done, testing_done)
        self.assertEqual(request.pk, review_request.pk)

    def test_review_detail_diff_comment_ordering(self):
        """Testing review_detail and ordering of diff comments on a review"""
        comment_text_1 = 'Comment text 1'
        comment_text_2 = 'Comment text 2'
        comment_text_3 = 'Comment text 3'

        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        # Create the users who will be commenting.
        user1 = User.objects.get(username='doc')
        user2 = User.objects.get(username='dopey')

        # Create the master review.
        main_review = self.create_review(review_request, user=user1)
        main_comment = self.create_diff_comment(main_review, filediff,
                                                text=comment_text_1)
        main_review.publish()

        # First reply
        reply1 = self.create_reply(
            main_review,
            user=user1,
            timestamp=(main_review.timestamp + timedelta(days=1)))
        self.create_diff_comment(reply1, filediff, text=comment_text_2,
                                 reply_to=main_comment)

        # Second reply
        reply2 = self.create_reply(
            main_review,
            user=user2,
            timestamp=(main_review.timestamp + timedelta(days=2)))
        self.create_diff_comment(reply2, filediff, text=comment_text_3,
                                 reply_to=main_comment)

        # Publish them out of order.
        reply2.publish()
        reply1.publish()

        # Make sure they published in the order expected.
        self.assertTrue(reply1.timestamp > reply2.timestamp)

        # Make sure they're looked up in the order expected.
        comments = list(
            Comment.objects
            .filter(review__review_request=review_request)
            .order_by('timestamp')
        )
        self.assertEqual(len(comments), 3)
        self.assertEqual(comments[0].text, comment_text_1)
        self.assertEqual(comments[1].text, comment_text_3)
        self.assertEqual(comments[2].text, comment_text_2)

        # Now figure out the order on the page.
        response = self.client.get('/r/%d/' % review_request.pk)
        self.assertEqual(response.status_code, 200)

        entries = response.context['entries']
        initial_entries = entries['initial']
        self.assertEqual(len(initial_entries), 1)
        self.assertIsInstance(initial_entries[0], InitialStatusUpdatesEntry)

        main_entries = entries['main']
        self.assertEqual(len(main_entries), 1)
        entry = main_entries[0]
        self.assertIsInstance(entry, ReviewEntry)
        comments = entry.comments['diff_comments']
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].text, comment_text_1)

        replies = comments[0].public_replies()
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0].text, comment_text_3)
        self.assertEqual(replies[1].text, comment_text_2)

    def test_review_detail_general_comment_ordering(self):
        """Testing review_detail and ordering of general comments on a review
        """
        comment_text_1 = 'Comment text 1'
        comment_text_2 = 'Comment text 2'
        comment_text_3 = 'Comment text 3'
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)
        # Create the users who will be commenting.
        user1 = User.objects.get(username='doc')
        user2 = User.objects.get(username='dopey')

        # Create the master review.
        main_review = self.create_review(review_request, user=user1)
        main_comment = self.create_general_comment(main_review,
                                                   text=comment_text_1)
        main_review.publish()

        # First reply
        reply1 = self.create_reply(
            main_review,
            user=user1,
            timestamp=(main_review.timestamp + timedelta(days=1)))
        self.create_general_comment(reply1, text=comment_text_2,
                                    reply_to=main_comment)

        # Second reply
        reply2 = self.create_reply(
            main_review,
            user=user2,
            timestamp=(main_review.timestamp + timedelta(days=2)))
        self.create_general_comment(reply2, text=comment_text_3,
                                    reply_to=main_comment)

        # Publish them out of order.
        reply2.publish()
        reply1.publish()

        # Make sure they published in the order expected.
        self.assertTrue(reply1.timestamp > reply2.timestamp)

        # Make sure they're looked up in the order expected.
        comments = list(
            GeneralComment.objects
            .filter(review__review_request=review_request)
            .order_by('timestamp')
        )
        self.assertEqual(len(comments), 3)
        self.assertEqual(comments[0].text, comment_text_1)
        self.assertEqual(comments[1].text, comment_text_3)
        self.assertEqual(comments[2].text, comment_text_2)

    def test_review_detail_file_attachment_visibility(self):
        """Testing visibility of file attachments on review requests"""
        caption_1 = 'File Attachment 1'
        caption_2 = 'File Attachment 2'
        caption_3 = 'File Attachment 3'
        comment_text_1 = 'Comment text 1'
        comment_text_2 = 'Comment text 2'

        user1 = User.objects.get(username='doc')
        review_request = self.create_review_request()

        # Add two file attachments. One active, one inactive.
        file1 = self.create_file_attachment(review_request, caption=caption_1)
        file2 = self.create_file_attachment(review_request, caption=caption_2,
                                            active=False)
        review_request.publish(user1)

        # Create a third file attachment on a draft.
        self.create_file_attachment(review_request, caption=caption_3,
                                    draft=True)

        # Create the review with comments for each screenshot.
        review = Review.objects.create(review_request=review_request,
                                       user=user1)
        review.file_attachment_comments.create(file_attachment=file1,
                                               text=comment_text_1)
        review.file_attachment_comments.create(file_attachment=file2,
                                               text=comment_text_2)
        review.publish()

        # Check that we can find all the objects we expect on the page.
        self.client.login(username='doc', password='doc')
        response = self.client.get('/r/%d/' % review_request.pk)
        self.assertEqual(response.status_code, 200)

        file_attachments = response.context['file_attachments']
        self.assertEqual(len(file_attachments), 2)
        self.assertEqual(file_attachments[0].caption, caption_1)
        self.assertEqual(file_attachments[1].caption, caption_3)

        # Make sure that other users won't see the draft one.
        self.client.logout()
        response = self.client.get('/r/%d/' % review_request.pk)
        self.assertEqual(response.status_code, 200)

        file_attachments = response.context['file_attachments']
        self.assertEqual(len(file_attachments), 1)
        self.assertEqual(file_attachments[0].caption, caption_1)

        # Make sure we loaded the reviews and all data correctly.
        entries = response.context['entries']
        initial_entries = entries['initial']
        self.assertEqual(len(initial_entries), 1)
        self.assertIsInstance(initial_entries[0], InitialStatusUpdatesEntry)

        main_entries = entries['main']
        self.assertEqual(len(main_entries), 1)
        entry = main_entries[0]
        self.assertIsInstance(entry, ReviewEntry)

        comments = entry.comments['file_attachment_comments']
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0].text, comment_text_1)
        self.assertEqual(comments[1].text, comment_text_2)

    def test_review_detail_screenshot_visibility(self):
        """Testing visibility of screenshots on review requests"""
        caption_1 = 'Screenshot 1'
        caption_2 = 'Screenshot 2'
        caption_3 = 'Screenshot 3'
        comment_text_1 = 'Comment text 1'
        comment_text_2 = 'Comment text 2'

        user1 = User.objects.get(username='doc')
        review_request = self.create_review_request()

        # Add two screenshots. One active, one inactive.
        screenshot1 = self.create_screenshot(review_request, caption=caption_1)
        screenshot2 = self.create_screenshot(review_request, caption=caption_2,
                                             active=False)
        review_request.publish(user1)

        # Add a third screenshot on a draft.
        self.create_screenshot(review_request, caption=caption_3, draft=True)

        # Create the review with comments for each screenshot.
        user1 = User.objects.get(username='doc')
        review = Review.objects.create(review_request=review_request,
                                       user=user1)
        review.screenshot_comments.create(screenshot=screenshot1,
                                          text=comment_text_1,
                                          x=10,
                                          y=10,
                                          w=20,
                                          h=20)
        review.screenshot_comments.create(screenshot=screenshot2,
                                          text=comment_text_2,
                                          x=0,
                                          y=0,
                                          w=10,
                                          h=10)
        review.publish()

        # Check that we can find all the objects we expect on the page.
        self.client.login(username='doc', password='doc')
        response = self.client.get('/r/%d/' % review_request.pk)
        self.assertEqual(response.status_code, 200)

        screenshots = response.context['screenshots']
        self.assertEqual(len(screenshots), 2)
        self.assertEqual(screenshots[0].caption, caption_1)
        self.assertEqual(screenshots[1].caption, caption_3)

        # Make sure that other users won't see the draft one.
        self.client.logout()
        response = self.client.get('/r/%d/' % review_request.pk)
        self.assertEqual(response.status_code, 200)

        screenshots = response.context['screenshots']
        self.assertEqual(len(screenshots), 1)
        self.assertEqual(screenshots[0].caption, caption_1)

        entries = response.context['entries']
        initial_entries = entries['initial']
        self.assertEqual(len(initial_entries), 1)
        self.assertIsInstance(initial_entries[0], InitialStatusUpdatesEntry)

        main_entries = entries['main']
        self.assertEqual(len(main_entries), 1)
        entry = main_entries[0]
        self.assertIsInstance(entry, ReviewEntry)

        # Make sure we loaded the reviews and all data correctly.
        comments = entry.comments['screenshot_comments']
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[0].text, comment_text_1)
        self.assertEqual(comments[1].text, comment_text_2)

    def test_review_detail_sitewide_login(self):
        """Testing review_detail view with site-wide login enabled"""
        self.siteconfig.set('auth_require_sitewide_login', True)
        self.siteconfig.save()

        self.create_review_request(publish=True)

        response = self.client.get('/r/1/')
        self.assertEqual(response.status_code, 302)

    def test_new_review_request(self):
        """Testing new_review_request view"""
        response = self.client.get('/r/new')
        self.assertEqual(response.status_code, 301)

        response = self.client.get('/r/new/')
        self.assertEqual(response.status_code, 302)

        self.client.login(username='grumpy', password='grumpy')

        response = self.client.get('/r/new/')
        self.assertEqual(response.status_code, 200)

    def test_new_review_request_in_read_only_mode_for_users(self):
        """Testing new_review_request view when in read-only mode for regular
        users
        """
        with self.override_siteconfig(site_read_only=True):
            # Ensure user is redirected when trying to create new review request
            self.client.logout()
            self.client.login(username='doc', password='doc')

            resp = self.client.get('/r/new/')

            self.assertEqual(resp.status_code, 302)

    def test_new_review_request_in_read_only_mode_for_superusers(self):
        """Testing new_review_request view when in read-only mode for
        superusers
        """
        with self.override_siteconfig(site_read_only=True):
            # Ensure admin can still access new while in read-only mode.
            self.client.logout()
            self.client.login(username='admin', password='admin')

            resp = self.client.get('/r/new/')

            self.assertEqual(resp.status_code, 200)

    # Bug 892
    def test_interdiff(self):
        """Testing the diff viewer with interdiffs"""
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request, revision=1)
        self.create_filediff(
            diffset,
            source_file='/diffutils.py',
            dest_file='/diffutils.py',
            source_revision='6bba278',
            dest_detail='465d217',
            diff=(
                b'diff --git a/diffutils.py b/diffutils.py\n'
                b'index 6bba278..465d217 100644\n'
                b'--- a/diffutils.py\n'
                b'+++ b/diffutils.py\n'
                b'@@ -1,3 +1,4 @@\n'
                b'+# diffutils.py\n'
                b' import fnmatch\n'
                b' import os\n'
                b' import re\n'
            ))
        self.create_filediff(
            diffset,
            source_file='/readme',
            dest_file='/readme',
            source_revision='d6613f5',
            dest_detail='5b50866',
            diff=(
                b'diff --git a/readme b/readme\n'
                b'index d6613f5..5b50866 100644\n'
                b'--- a/readme\n'
                b'+++ b/readme\n'
                b'@@ -1 +1,3 @@\n'
                b' Hello there\n'
                b'+\n'
                b'+Oh hi!\n'
            ))
        self.create_filediff(
            diffset,
            source_file='/newfile',
            dest_file='/newfile',
            source_revision='PRE-CREATION',
            dest_detail='',
            diff=(
                b'diff --git a/new_file b/new_file\n'
                b'new file mode 100644\n'
                b'index 0000000..ac30bd3\n'
                b'--- /dev/null\n'
                b'+++ b/new_file\n'
                b'@@ -0,0 +1 @@\n'
                b'+This is a new file!\n'
            ))

        diffset = self.create_diffset(review_request, revision=2)
        self.create_filediff(
            diffset,
            source_file='/diffutils.py',
            dest_file='/diffutils.py',
            source_revision='6bba278',
            dest_detail='465d217',
            diff=(
                b'diff --git a/diffutils.py b/diffutils.py\n'
                b'index 6bba278..465d217 100644\n'
                b'--- a/diffutils.py\n'
                b'+++ b/diffutils.py\n'
                b'@@ -1,3 +1,4 @@\n'
                b'+# diffutils.py\n'
                b' import fnmatch\n'
                b' import os\n'
                b' import re\n'
            ))
        self.create_filediff(
            diffset,
            source_file='/readme',
            dest_file='/readme',
            source_revision='d6613f5',
            dest_detail='5b50867',
            diff=(
                b'diff --git a/readme b/readme\n'
                b'index d6613f5..5b50867 100644\n'
                b'--- a/readme\n'
                b'+++ b/readme\n'
                b'@@ -1 +1,3 @@\n'
                b' Hello there\n'
                b'+----------\n'
                b'+Oh hi!\n'
            ))
        self.create_filediff(
            diffset,
            source_file='/newfile',
            dest_file='/newfile',
            source_revision='PRE-CREATION',
            dest_detail='',
            diff=(
                b'diff --git a/new_file b/new_file\n'
                b'new file mode 100644\n'
                b'index 0000000..ac30bd4\n'
                b'--- /dev/null\n'
                b'+++ b/new_file\n'
                b'@@ -0,0 +1 @@\n'
                b'+This is a diffent version of this new file!\n'
            ))

        response = self.client.get('/r/1/diff/1-2/')

        # Useful for debugging any actual errors here.
        if response.status_code != 200:
            print('Error: %s' % self._get_context_var(response, 'error'))
            print(self._get_context_var(response, 'trace'))

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self._get_context_var(response, 'diff_context')['num_diffs'],
            2)

        files = self._get_context_var(response, 'files')
        self.assertTrue(files)
        self.assertEqual(len(files), 2)

        self.assertEqual(files[0]['depot_filename'], '/newfile')
        self.assertIn('interfilediff', files[0])

        self.assertEqual(files[1]['depot_filename'], '/readme')
        self.assertIn('interfilediff', files[1])

    # Bug 847
    def test_interdiff_new_file(self):
        """Testing the diff viewer with interdiffs containing new files"""
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request, revision=1)
        self.create_filediff(
            diffset,
            source_file='/diffutils.py',
            dest_file='/diffutils.py',
            source_revision='6bba278',
            dest_detail='465d217',
            diff=(
                b'diff --git a/diffutils.py b/diffutils.py\n'
                b'index 6bba278..465d217 100644\n'
                b'--- a/diffutils.py\n'
                b'+++ b/diffutils.py\n'
                b'@@ -1,3 +1,4 @@\n'
                b'+# diffutils.py\n'
                b' import fnmatch\n'
                b' import os\n'
                b' import re\n'
            ))

        diffset = self.create_diffset(review_request, revision=2)
        self.create_filediff(
            diffset,
            source_file='/diffutils.py',
            dest_file='/diffutils.py',
            source_revision='6bba278',
            dest_detail='465d217',
            diff=(
                b'diff --git a/diffutils.py b/diffutils.py\n'
                b'index 6bba278..465d217 100644\n'
                b'--- a/diffutils.py\n'
                b'+++ b/diffutils.py\n'
                b'@@ -1,3 +1,4 @@\n'
                b'+# diffutils.py\n'
                b' import fnmatch\n'
                b' import os\n'
                b' import re\n'
            ))
        self.create_filediff(
            diffset,
            source_file='/newfile',
            dest_file='/newfile',
            source_revision='PRE-CREATION',
            dest_detail='',
            diff=(
                b'diff --git a/new_file b/new_file\n'
                b'new file mode 100644\n'
                b'index 0000000..ac30bd4\n'
                b'--- /dev/null\n'
                b'+++ b/new_file\n'
                b'@@ -0,0 +1 @@\n'
                b'+This is a diffent version of this new file!\n'
            ))

        response = self.client.get('/r/1/diff/1-2/')

        # Useful for debugging any actual errors here.
        if response.status_code != 200:
            print('Error: %s' % self._get_context_var(response, 'error'))
            print(self._get_context_var(response, 'trace'))

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self._get_context_var(response, 'diff_context')['num_diffs'],
            2)

        files = self._get_context_var(response, 'files')
        self.assertTrue(files)
        self.assertEqual(len(files), 1)

        self.assertEqual(files[0]['depot_filename'], '/newfile')
        self.assertIn('interfilediff', files[0])

    def test_review_request_etag_with_issues(self):
        """Testing review request ETags with issue status toggling"""
        self.client.login(username='doc', password='doc')

        # Some objects we need.
        user = User.objects.get(username='doc')

        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        # Create a review.
        review = self.create_review(review_request, user=user)
        comment = self.create_diff_comment(review, filediff,
                                           issue_opened=True)
        review.publish()

        # Get the etag
        response = self.client.get(review_request.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        etag1 = response['ETag']
        self.assertNotEqual(etag1, '')

        # Change the issue status
        comment.issue_status = Comment.RESOLVED
        comment.save()

        # Check the etag again
        response = self.client.get(review_request.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        etag2 = response['ETag']
        self.assertNotEqual(etag2, '')

        # Make sure they're not equal
        self.assertNotEqual(etag1, etag2)

    # Bug #3384
    def test_diff_raw_content_disposition_attachment(self):
        """Testing /diff/raw/ Content-Disposition: attachment; ..."""
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)

        self.create_diffset(review_request=review_request)

        response = self.client.get('/r/%d/diff/raw/' % review_request.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Disposition'],
                         'attachment; filename=diffset')

    # Bug #3704
    def test_diff_raw_multiple_content_disposition(self):
        """Testing /diff/raw/ multiple Content-Disposition issue"""
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)

        # Create a diffset with a comma in its name.
        self.create_diffset(review_request=review_request, name='test, comma')

        response = self.client.get('/r/%d/diff/raw/' % review_request.pk)
        content_disposition = response['Content-Disposition']
        filename = content_disposition[len('attachment; filename='):]
        self.assertFalse(',' in filename)

    # Bug #4080
    def test_bug_url_with_custom_scheme(self):
        """Testing whether bug url with non-HTTP scheme loads correctly"""
        # Create a repository with a bug tracker that uses a non-standard
        # url scheme.
        repository = self.create_repository(public=True,
                                            bug_tracker='scheme://bugid=%s')
        review_request = self.create_review_request(repository=repository,
                                                    publish=True)
        url = reverse('bug_url', args=(review_request.pk, '1'))
        response = self.client.get(url)

        # Test if we redirected to the correct url with correct bugID.
        self.assertEqual(response['Location'], 'scheme://bugid=1')

    def test_preview_review_request_email_access_with_debug(self):
        """Testing preview_review_request_email access with DEBUG=True"""
        review_request = self.create_review_request(publish=True)

        with self.settings(DEBUG=True):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-request-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'message_format': 'text',
                    }))

        self.assertEqual(response.status_code, 200)

    def test_preview_review_request_email_access_without_debug(self):
        """Testing preview_review_request_email access with DEBUG=False"""
        review_request = self.create_review_request(publish=True)

        with self.settings(DEBUG=False):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-request-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'message_format': 'text',
                    }))

        self.assertEqual(response.status_code, 404)

    def test_preview_review_request_email_with_valid_change_id(self):
        """Testing preview_review_request_email access with valid change ID"""
        user = User.objects.create_user('test user')
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True,
                                                    target_people=[user])

        self.create_diffset(review_request, draft=True)
        review_request.publish(review_request.submitter)

        with self.settings(DEBUG=True):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-request-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'message_format': 'text',
                        'changedesc_id': review_request.changedescs.get().pk,
                    }))

        self.assertEqual(response.status_code, 200)

    def test_preview_review_request_email_with_invalid_change_id(self):
        """Testing preview_review_request_email access with invalid change ID
        """
        user = User.objects.create_user('test user')
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True,
                                                    target_people=[user])

        self.create_diffset(review_request, draft=True)
        review_request.publish(review_request.submitter)

        with self.settings(DEBUG=True):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-request-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'message_format': 'text',
                        'changedesc_id': 100,
                    }))

        self.assertEqual(response.status_code, 404)

    def test_preview_review_email_access_with_debug(self):
        """Testing preview_review_email access with DEBUG=True"""
        review_request = self.create_review_request(publish=True)
        review = self.create_review(review_request, publish=True)

        with self.settings(DEBUG=True):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'review_id': review.pk,
                        'message_format': 'text',
                    }))

        self.assertEqual(response.status_code, 200)

    def test_preview_review_email_access_without_debug(self):
        """Testing preview_review_email access with DEBUG=False"""
        review_request = self.create_review_request(publish=True)
        review = self.create_review(review_request, publish=True)

        with self.settings(DEBUG=False):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'review_id': review.pk,
                        'message_format': 'text',
                    }))

        self.assertEqual(response.status_code, 404)

    def test_preview_review_reply_email_access_with_debug(self):
        """Testing preview_review_reply_email access with DEBUG=True"""
        review_request = self.create_review_request(publish=True)
        review = self.create_review(review_request, publish=True)
        reply = self.create_reply(review, publish=True)

        with self.settings(DEBUG=True):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-reply-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'review_id': review.pk,
                        'reply_id': reply.pk,
                        'message_format': 'text',
                    }))

        self.assertEqual(response.status_code, 200)

    def test_preview_review_reply_email_access_without_debug(self):
        """Testing preview_review_reply_email access with DEBUG=False"""
        review_request = self.create_review_request(publish=True)
        review = self.create_review(review_request, publish=True)
        reply = self.create_reply(review, publish=True)

        with self.settings(DEBUG=False):
            response = self.client.get(
                local_site_reverse(
                    'preview-review-reply-email',
                    kwargs={
                        'review_request_id': review_request.pk,
                        'review_id': review.pk,
                        'reply_id': reply.pk,
                        'message_format': 'text',
                    }))

        self.assertEqual(response.status_code, 404)

    def test_view_screenshot_access_with_valid_id(self):
        """Testing view_screenshot access with valid screenshot for review
        request
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_view_screenshot_access_with_valid_id_and_draft(self):
        """Testing view_screenshot access with valid screenshot for review
        request draft
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request, draft=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_view_screenshot_access_with_valid_inactive_id(self):
        """Testing view_screenshot access with valid inactive screenshot for
        review request
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request, active=False)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_view_screenshot_access_with_valid_inactive_id_and_draft(self):
        """Testing view_screenshot access with valid inactive screenshot for
        review request draft
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request, draft=True,
                                            active=False)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_view_screenshot_access_with_invalid_id(self):
        """Testing view_screenshot access with invalid screenshot for review
        request
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request)

        review_request2 = self.create_review_request(publish=True)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_view_screenshot_access_with_invalid_id_and_draft(self):
        """Testing view_screenshot access with invalid screenshot for review
        request draft
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request, draft=True)

        review_request2 = self.create_review_request(publish=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_view_screenshot_access_with_invalid_inactive_id(self):
        """Testing view_screenshot access with invalid inactive screenshot
        for review request
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request, active=False)

        review_request2 = self.create_review_request(publish=True)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_view_screenshot_access_with_invalid_inactive_id_and_draft(self):
        """Testing view_screenshot access with invalid inactive screenshot
        for review request draft
        """
        review_request = self.create_review_request(publish=True)
        screenshot = self.create_screenshot(review_request, draft=True,
                                            active=False)

        review_request2 = self.create_review_request(publish=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'screenshot',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'screenshot_id': screenshot.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_review_file_attachment_access_with_valid_id(self):
        """Testing review_file_attachment access with valid attachment for
        review request
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_review_file_attachment_access_with_valid_id_and_draft(self):
        """Testing review_file_attachment access with valid attachment for
        review request draft
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request, draft=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_review_file_attachment_access_with_invalid_id(self):
        """Testing review_file_attachment access with invalid attachment for
        review request
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request)

        review_request2 = self.create_review_request(publish=True)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_review_file_attachment_access_with_invalid_id_and_draft(self):
        """Testing review_file_attachment access with invalid attachment for
        review request draft
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request, draft=True)

        review_request2 = self.create_review_request(publish=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_review_file_attachment_access_with_valid_inactive_id(self):
        """Testing review_file_attachment access with valid inactive
        attachment for review request
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request, active=False)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_review_file_attachment_access_with_valid_inactive_id_draft(self):
        """Testing review_file_attachment access with valid inactive
        attachment for review request draft
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request, draft=True,
                                                 active=False)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_review_file_attachment_access_with_invalid_inactive_id(self):
        """Testing review_file_attachment access with invalid inactive
        attachment for review request
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request, active=False)

        review_request2 = self.create_review_request(publish=True)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_review_file_attachment_access_invalid_inactive_id_draft(self):
        """Testing review_file_attachment access with invalid inactive
        attachment for review request draft
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request, draft=True,
                                                 active=False)

        review_request2 = self.create_review_request(publish=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request2.pk,
                    'file_attachment_id': attachment.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_review_file_attachment_access_with_valid_diff_against_id(self):
        """Testing review_file_attachment access with valid diff-against
        attachment for review request
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request)
        attachment2 = self.create_file_attachment(review_request)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                    'file_attachment_diff_id': attachment2.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_review_file_attachment_access_valid_diff_against_id_draft(self):
        """Testing review_file_attachment access with valid diff-against
        attachment for review request draft
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request)
        attachment2 = self.create_file_attachment(review_request, draft=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                    'file_attachment_diff_id': attachment2.pk,
                }))
        self.assertEqual(response.status_code, 200)

    def test_review_file_attachment_access_with_invalid_diff_against_id(self):
        """Testing review_file_attachment access with invalid diff-against
        attachment for review request
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request)

        review_request2 = self.create_review_request(publish=True)
        attachment2 = self.create_file_attachment(review_request2)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                    'file_attachment_diff_id': attachment2.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def test_review_file_attachment_access_invalid_diff_against_id_draft(self):
        """Testing review_file_attachment access with invalid diff-against
        attachment for review request draft
        """
        review_request = self.create_review_request(publish=True)
        attachment = self.create_file_attachment(review_request)

        review_request2 = self.create_review_request(publish=True)
        attachment2 = self.create_file_attachment(review_request2, draft=True)

        # Log in so that we can check against the draft.
        username = review_request.submitter.username
        self.client.login(username=username, password=username)

        response = self.client.get(
            local_site_reverse(
                'file-attachment',
                kwargs={
                    'review_request_id': review_request.pk,
                    'file_attachment_id': attachment.pk,
                    'file_attachment_diff_id': attachment2.pk,
                }))
        self.assertEqual(response.status_code, 404)

    def _get_context_var(self, response, varname):
        for context in response.context:
            if varname in context:
                return context[varname]

        return None


class CommentDiffFragmentsViewTests(TestCase):
    """Unit tests for the comment_diff_fragments view."""

    fixtures = ['test_users', 'test_scmtools']

    def test_get_with_unpublished_review_request_not_owner(self):
        """Testing comment_diff_fragments with unpublished review request and
        user is not the owner
        """
        user = User.objects.create_user(username='reviewer',
                                        password='reviewer',
                                        email='reviewer@example.com')

        review_request = self.create_review_request(create_repository=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request, user=user)
        comment1 = self.create_diff_comment(review, filediff)
        comment2 = self.create_diff_comment(review, filediff)
        review.publish()

        self.assertTrue(self.client.login(username='reviewer',
                                          password='reviewer'))

        self._get_fragments(review_request,
                            [comment1.pk, comment2.pk],
                            expected_status=403)

    def test_get_with_unpublished_review_request_owner(self):
        """Testing comment_diff_fragments with unpublished review request and
        user is the owner
        """
        user = User.objects.create_user(username='test-user',
                                        password='test-user',
                                        email='user@example.com')

        review_request = self.create_review_request(create_repository=True,
                                                    submitter=user)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request, user=user)
        comment1 = self.create_diff_comment(review, filediff)
        comment2 = self.create_diff_comment(review, filediff)
        review.publish()

        self.assertTrue(self.client.login(username='test-user',
                                          password='test-user'))

        fragments = self._get_fragments(review_request,
                                        [comment1.pk, comment2.pk])
        self.assertEqual(len(fragments), 2)
        self.assertEqual(fragments[0][0], comment1.pk)
        self.assertEqual(fragments[1][0], comment2.pk)

    @add_fixtures(['test_site'])
    def test_get_with_published_review_request_local_site_access(self):
        """Testing comment_diff_fragments with published review request on
        a Local Site the user has access to
        """
        user = User.objects.create_user(username='test-user',
                                        password='test-user',
                                        email='user@example.com')

        review_request = self.create_review_request(create_repository=True,
                                                    with_local_site=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request)
        comment1 = self.create_diff_comment(review, filediff)
        comment2 = self.create_diff_comment(review, filediff)
        review.publish()

        review_request.local_site.users.add(user)

        self.assertTrue(self.client.login(username='test-user',
                                          password='test-user'))

        fragments = self._get_fragments(review_request,
                                        [comment1.pk, comment2.pk],
                                        local_site_name='local-site-1')
        self.assertEqual(len(fragments), 2)
        self.assertEqual(fragments[0][0], comment1.pk)
        self.assertEqual(fragments[1][0], comment2.pk)

    @add_fixtures(['test_site'])
    def test_get_with_published_review_request_local_site_no_access(self):
        """Testing comment_diff_fragments with published review request on
        a Local Site the user does not have access to
        """
        User.objects.create_user(username='test-user',
                                 password='test-user',
                                 email='user@example.com')

        review_request = self.create_review_request(create_repository=True,
                                                    with_local_site=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request)
        comment1 = self.create_diff_comment(review, filediff)
        comment2 = self.create_diff_comment(review, filediff)
        review.publish()

        self.assertTrue(self.client.login(username='test-user',
                                          password='test-user'))

        self._get_fragments(review_request,
                            [comment1.pk, comment2.pk],
                            local_site_name='local-site-1',
                            expected_status=403)

    def test_get_with_unicode(self):
        """Testing comment_diff_fragments with Unicode content"""
        user = User.objects.create(username='reviewer')

        repository = self.create_repository(tool_name='Test')
        review_request = self.create_review_request(repository=repository,
                                                    publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(
            diffset,
            source_file='/data:áéíóú🔥',
            dest_file='/data:ÄËÏÖÜŸ',
            diff=(
                'diff --git a/data b/data\n'
                'index abcd123..abcd124 100644\n'
                '--- a/data\n'
                '+++ b/data\n'
                '@@ -1,1 +1,1 @@\n'
                '-áéíóú🔥\n'
                '+ÄËÏÖÜŸ\n'
            ).encode('utf-8'))

        review = self.create_review(review_request, user=user)
        comment1 = self.create_diff_comment(review, filediff)
        comment2 = self.create_diff_comment(review, filediff)
        review.publish()

        fragments = self._get_fragments(review_request,
                                        [comment1.pk, comment2.pk])
        self.assertEqual(len(fragments), 2)

        comment_id, html = fragments[0]
        self.assertEqual(comment_id, comment1.pk)
        self.assertTrue(html.startswith('<table class="sidebyside'))
        self.assertTrue(html.endswith('</table>'))
        self.assertIn('áéíóú🔥', html)

        comment_id, html = fragments[1]
        self.assertEqual(comment_id, comment2.pk)
        self.assertTrue(html.startswith('<table class="sidebyside'))
        self.assertTrue(html.endswith('</table>'))
        self.assertIn('ÄËÏÖÜŸ', html)

    def test_get_with_valid_comment_ids(self):
        """Testing comment_diff_fragments with valid comment ID"""
        user = User.objects.create_user(username='reviewer',
                                        email='reviewer@example.com')

        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request, user=user)
        comment1 = self.create_diff_comment(review, filediff)
        comment2 = self.create_diff_comment(review, filediff)
        review.publish()

        fragments = self._get_fragments(review_request,
                                        [comment1.pk, comment2.pk])
        self.assertEqual(len(fragments), 2)
        self.assertEqual(fragments[0][0], comment1.pk)
        self.assertEqual(fragments[1][0], comment2.pk)

    def test_get_with_valid_and_invalid_comment_ids(self):
        """Testing comment_diff_fragments with mix of valid comment IDs and
        comment IDs not found in database
        """
        user = User.objects.create_user(username='reviewer',
                                        email='reviewer@example.com')

        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request, user=user)
        comment = self.create_diff_comment(review, filediff)
        review.publish()

        fragments = self._get_fragments(review_request, [999, comment.pk])
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0][0], comment.pk)

    def test_get_with_no_valid_comment_ids(self):
        """Testing comment_diff_fragments with no valid comment IDs"""
        review_request = self.create_review_request(create_repository=True,
                                                    publish=True)

        self._get_fragments(review_request,
                            [100, 200, 300],
                            expected_status=404)

    def test_get_with_comment_ids_from_other_review_request(self):
        """Testing comment_diff_fragments with comment ID from another review
        request
        """
        user = User.objects.create_user(username='reviewer',
                                        email='reviewer@example.com')

        # Create the first review request and review.
        review_request1 = self.create_review_request(create_repository=True,
                                                     publish=True)
        diffset = self.create_diffset(review_request1)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request1, user=user)
        comment1 = self.create_diff_comment(review, filediff)
        review.publish()

        # Create the second review request and review.
        review_request2 = self.create_review_request(create_repository=True,
                                                     publish=True)
        diffset = self.create_diffset(review_request2)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request2, user=user)
        comment2 = self.create_diff_comment(review, filediff)
        review.publish()

        fragments = self._get_fragments(review_request1,
                                        [comment1.pk, comment2.pk])
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0][0], comment1.pk)

    def test_get_with_comment_ids_from_draft_review_owner(self):
        """Testing comment_diff_fragments with comment ID from draft review,
        accessed by the review's owner
        """
        user = User.objects.create_user(username='reviewer',
                                        password='reviewer',
                                        email='reviewer@example.com')

        review_request1 = self.create_review_request(create_repository=True,
                                                     publish=True)
        diffset = self.create_diffset(review_request1)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request1, user=user)
        comment = self.create_diff_comment(review, filediff)

        self.assertTrue(self.client.login(username='reviewer',
                                          password='reviewer'))

        fragments = self._get_fragments(review_request1, [comment.pk])
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0][0], comment.pk)

    def test_get_with_comment_ids_from_draft_review_not_owner(self):
        """Testing comment_diff_fragments with comment ID from draft review,
        accessed by someone other than the review's owner
        """
        user = User.objects.create_user(username='reviewer',
                                        email='reviewer@example.com')

        review_request1 = self.create_review_request(create_repository=True,
                                                     publish=True)
        diffset = self.create_diffset(review_request1)
        filediff = self.create_filediff(diffset)

        review = self.create_review(review_request1, user=user)
        comment = self.create_diff_comment(review, filediff)

        self._get_fragments(review_request1,
                            [comment.pk],
                            expected_status=404)

    def _get_fragments(self, review_request, comment_ids,
                       local_site_name=None, expected_status=200):
        """Load and return fragments from the server.

        Args:
            review_request (reviewboard.reviews.models.review_request.
                            ReviewRequest):
                The review request the comments were made on.

            comment_ids (list of int):
                The list of comment IDs to load.

            local_site_name (unicode, optional):
                The name of the Local Site for the URL.

            expected_status (int, optional):
                The expected HTTP status code. By default, this is a
                successful 200.

        Returns:
            list of tuple:
            A list of ``(comment_id, html)`` from the parsed payload, if
            the status code was 200.
        """
        response = self.client.get(
            local_site_reverse(
                'diff-comment-fragments',
                kwargs={
                    'review_request_id': review_request.display_id,
                    'comment_ids': ','.join(
                        six.text_type(comment_id)
                        for comment_id in comment_ids
                    ),
                },
                local_site_name=local_site_name))
        self.assertEqual(response.status_code, expected_status)

        if expected_status != 200:
            return None

        content = response.content
        self.assertIs(type(content), bytes)

        i = 0
        results = []

        while i < len(content):
            # Read the comment ID.
            comment_id = struct.unpack_from('<L', content, i)[0]
            i += 4

            # Read the length of the HTML.
            html_len = struct.unpack_from('<L', content, i)[0]
            i += 4

            # Read the HTML.
            html = content[i:i + html_len].decode('utf-8')
            i += html_len

            results.append((comment_id, html))

        return results


class DownloadFileTests(TestCase):
    """Tests for the download_*_file views."""

    fixtures = ['test_users', 'test_scmtools']

    @classmethod
    def setUpClass(cls):
        super(DownloadFileTests, cls).setUpClass()

        register_hosting_service(TestService.name, TestService)

    @classmethod
    def tearDownClass(cls):
        super(DownloadFileTests, cls).tearDownClass()

        unregister_hosting_service(TestService.name)

    def setUp(self):
        super(DownloadFileTests, self).setUp()

        self.account = HostingServiceAccount.objects.create(
            service_name=TestService.name,
            hosting_url='http://example.com/',
            username='foo')

        self.repository = self.create_repository(hosting_account=self.account)
        self.review_request = self.create_review_request(
            repository=self.repository, publish=True)
        self.diffset = self.create_diffset(review_request=self.review_request)
        self.filediff = self.create_filediff(self.diffset,
                                             source_file='/invalid-path',
                                             dest_file='/invalid-path')

    def testing_download_orig_file_404(self):
        """Testing download_orig_file when the file cannot be found upstream"""
        rsp = self.client.get(
            local_site_reverse('download-orig-file', kwargs={
                'review_request_id': self.review_request.display_id,
                'revision': self.diffset.revision,
                'filediff_id': self.filediff.pk,
            }))

        self.assertEquals(rsp.status_code, 404)

    def testing_download_modified_file_404(self):
        """Testing download_modified_file when the file cannot be found
        upstream
        """
        rsp = self.client.get(
            local_site_reverse('download-modified-file', kwargs={
                'review_request_id': self.review_request.display_id,
                'revision': self.diffset.revision,
                'filediff_id': self.filediff.pk,
            }))

        self.assertEquals(rsp.status_code, 404)


class UserInfoboxTests(TestCase):
    def test_unicode(self):
        """Testing user_infobox with a user with non-ascii characters"""
        user = User.objects.create_user('test', 'test@example.com')
        user.first_name = 'Test\u21b9'
        user.last_name = 'User\u2729'
        user.save()

        self.client.get(local_site_reverse('user-infobox', args=['test']))
