# -*- coding: utf-8 -*-

from __future__ import absolute_import

import logging

import collections

from sqlalchemy import event

from ...pub.sqlalchemy import sqlalchemy_pub
from ...signals import signal


class sqlalchemy_es_pub(sqlalchemy_pub):
    """SQLAlchemy EventSourcing Pub.

    Add eventsourcing to sqlalchemy_pub, three more signals added for tables:

    * ``session_prepare``
    * ``session_commit`` / ``session_rollback``

    The hook will use prepare-commit pattern to ensure 100% reliability on
    event sourcing.
    """
    logger = logging.getLogger("meepo.pub.sqlalchemy_es_pub")

    def _install(self):
        event.listen(self.session, "before_flush", self.session_update)

        # enable session prepare-commit hook
        event.listen(self.session, "after_flush", self.session_prepare)
        event.listen(self.session, "after_commit", self.session_commit)
        event.listen(self.session, "after_rollback", self.session_rollback)

    def session_prepare(self, session, _):
        """Send session_prepare signal in session "before_commit".

        The signal contains another event argument, which records whole info
        of what's changed in this session, so the signal receiver can receive
        and record the event.
        """
        if not hasattr(session, 'meepo_unique_id'):
            self._session_init(session)

        evt = collections.defaultdict(set)
        for action in ("write", "update", "delete"):
            objs = getattr(session, "pending_%s" % action)
            # filter tables if possible
            if self.tables:
                objs = [o for o in objs
                        if o.__table__.fullname in self.tables]
            for obj in objs:
                evt_name = "%s_%s" % (obj.__table__.fullname, action)
                evt[evt_name].add(self._pk(obj))
                self.logger.debug("%s - session_prepare: %s -> %s" % (
                    session.meepo_unique_id, evt_name, evt))

        # only trigger signal when event exists
        if evt:
            signal("session_prepare").send(session, event=evt)

    def session_commit(self, session):
        """Send session_commit signal in sqlalchemy ``before_commit``.

        This marks the success of session so the session may enter commit
        state.
        """
        # this may happen when there's nothing to commit
        if not hasattr(session, 'meepo_unique_id'):
            self.logger.debug("skipped - session_commit")
            return

        # normal session pub
        self.logger.debug("%s - session_commit" % session.meepo_unique_id)
        self._session_pub(session)
        signal("session_commit").send(session)
        self._session_del(session)

    def session_rollback(self, session):
        """Send session_rollback signal in sqlalchemy ``after_rollback``.

        This marks the failure of session so the session may enter commit
        phase.
        """
        # this may happen when there's nothing to rollback
        if not hasattr(session, 'meepo_unique_id'):
            self.logger.debug("skipped - session_rollback")
            return

        # del session meepo id after rollback
        self.logger.debug("%s - after_rollback" % session.meepo_unique_id)
        signal("session_rollback").send(session)
        self._session_del(session)
