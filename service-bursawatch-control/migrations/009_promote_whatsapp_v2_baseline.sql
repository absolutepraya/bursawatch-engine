-- bursawatch-release: manual

-- Promote only the untouched source-owned WhatsApp baseline. A dashboard or
-- other operator revision must remain authoritative and block this correction.
insert into bursawatch_config_revisions
    (watcher_id, revision, config_version, config, config_sha256, actor_id)
select w.watcher_id,
       2,
       2,
       $wa${"profiles":[{"additional_prompt_instruction":"Forward only material issuer events or disclosures, factual market or macro developments, coherent macro roundups, and exact leading #TechnicalReview posts. Reject promotions, product activation, calls to action, analyst research, stock picks, watchlists, outlooks, valuations, targets, and untagged technical or price-level material. Route an exact leading #TechnicalReview post to id_stocks_swing. Use id_stocks_news for one clear lead issuer in a multi-stock post, and macro_news for broad sector or market theses even when a top pick is named. Preserve explicit source statuses without inventing them.","channel_jid":"120363419226413141@newsletter","channel_url":"https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c","discord_channels":[{"channel_id":"1531655369884045382","description":"Broad Indonesian market, sector, infrastructure, and economy theses.","key":"macro_news"},{"channel_id":"1525102508714889257","description":"Direct IDX issuer news, earnings, dividends, corporate actions, fundamentals, and valuation.","key":"id_stocks_news"},{"channel_id":"1525102458253217803","description":"IDX technical-review posts beginning with #TechnicalReview.","key":"id_stocks_swing"}],"display_name":"BRI Danareksa Sekuritas","emoji":"<:bridanareksa:1549256273109848124>","enable_llm_relevance_filter":true,"enable_llm_routing":true,"enable_llm_summary":true,"enable_llm_title":true,"enabled":true,"forward_media":true,"id":"bri-danareksa-sekuritas","max_items_per_poll":20,"mode":"forward","relevance_scope":"stock_market","status_emojis":{"down":"<:down:1531285063986053200>","hold":"<:hold:1531284248235868333>","up":"<:up:1531285100346740766>"}},{"additional_prompt_instruction":"","channel_jid":"120363405187024421@newsletter","channel_url":"https://whatsapp.com/channel/0029Vb6qi96ISTkJcDn4op2z","discord_channels":[],"display_name":"INS","emoji":null,"enable_llm_relevance_filter":false,"enable_llm_routing":false,"enable_llm_summary":false,"enable_llm_title":false,"enabled":true,"forward_media":false,"id":"ins","max_items_per_poll":20,"mode":"observe","relevance_scope":"financial_market","status_emojis":{"down":null,"hold":null,"up":null}},{"additional_prompt_instruction":"","channel_jid":"120363319274271353@newsletter","channel_url":"https://whatsapp.com/channel/0029VagNdGpFMqrXKEcdBb2U","discord_channels":[],"display_name":"Samuel Sekuritas Indonesia","emoji":null,"enable_llm_relevance_filter":false,"enable_llm_routing":false,"enable_llm_summary":false,"enable_llm_title":false,"enabled":true,"forward_media":false,"id":"samuel-sekuritas-indonesia","max_items_per_poll":20,"mode":"observe","relevance_scope":"financial_market","status_emojis":{"down":null,"hold":null,"up":null}}],"version":2}$wa$::jsonb,
       '12c37e0c385f6b2431f2d318559d49406b9cb847fc5da8007459d06486602de9',
       'source-baseline-correction'
  from bursawatch_watchers w
  join bursawatch_config_revisions r
    on r.watcher_id = w.watcher_id
   and r.revision = 1
 where w.watcher_id = 'bursawatch-wa-channel-watch'
   and w.current_revision = 1
   and r.config_version = 1
   and r.config_sha256 = '11f80d21ef137ec2c3f92b5bc69e8e7146a331ceec0a2d46549e21bb17bbd829'
   and r.actor_id = 'source-baseline'
on conflict (watcher_id, revision) do nothing;

update bursawatch_watchers w
   set current_revision = 2,
       updated_at = now()
 where w.watcher_id = 'bursawatch-wa-channel-watch'
   and w.current_revision = 1
   and exists (
       select 1
         from bursawatch_config_revisions r
        where r.watcher_id = w.watcher_id
          and r.revision = 1
          and r.config_version = 1
          and r.config_sha256 = '11f80d21ef137ec2c3f92b5bc69e8e7146a331ceec0a2d46549e21bb17bbd829'
          and r.actor_id = 'source-baseline'
   )
   and exists (
       select 1
         from bursawatch_config_revisions r
        where r.watcher_id = w.watcher_id
          and r.revision = 2
          and r.config_version = 2
          and r.config_sha256 = '12c37e0c385f6b2431f2d318559d49406b9cb847fc5da8007459d06486602de9'
          and r.actor_id = 'source-baseline-correction'
   );
