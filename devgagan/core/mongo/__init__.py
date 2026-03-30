# MongoDB database module
from devgagan.core.mongo.db import (
    get_data,
    set_thumbnail,
    set_caption,
    replace_caption,
    set_session,
    clean_words,
    remove_clean_words,
    set_channel,
    all_words_remove,
    remove_thumbnail,
    remove_caption,
    remove_replace,
    remove_session,
    remove_channel,
    delete_session,
    set_topic_msg_ids,
    get_topic_msg_ids,
    clear_topic_msg_ids,
    save_batch_state,
    get_active_batch,
    update_batch_progress,
    clear_batch_state,
)

# Re-export db for backwards compatibility
from devgagan.core.mongo import db
