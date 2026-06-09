// TikTok + Instagram scrapers (Node) for the social radar.
// Uses drawrowfly's tiktok-scraper + instatouch. Runs on the GitHub Actions
// runner (clean IP). Writes social.json which scrape.py merges into feed.json.
//
// Both need a session cookie for real data (set as repo secrets):
//   TIKTOK_SESSION = your TikTok 'sid_tt' cookie value
//   IG_SESSION     = your Instagram 'sessionid' cookie value
//   IG_ACCOUNTS    = comma-separated IG handles to watch (default: minecraft)
// Missing cookies -> that source returns [] (graceful).

const fs = require("fs");

const NICHE = ["minecraft","mc","block","creeper","build","survival",
  "redstone","speedrun","nether","shorts","gaming","mcyt"];
const rel = (t) => { t = (t || "").toLowerCase(); return NICHE.some((k) => t.includes(k)); };

async function tiktok() {
  try {
    const TikTokScraper = require("tiktok-scraper");
    const sess = process.env.TIKTOK_SESSION;
    const opts = { number: 40, ...(sess ? { sessionList: [`sid_tt=${sess}`] } : {}) };
    const res = await TikTokScraper.trend("", opts);
    const out = [];
    for (const v of (res.collector || [])) {
      if (!rel(v.text)) continue;
      const author = (v.authorMeta && v.authorMeta.name) || "";
      const tag = (v.hashtags && v.hashtags[0] && v.hashtags[0].name) || "";
      out.push({
        id: "tt" + v.id,
        title: (v.text || "(tiktok)").slice(0, 90),
        url: `https://www.tiktok.com/@${author}/video/${v.id}`,
        author, views: v.playCount || null, tag,
      });
    }
    out.sort((a, b) => (b.views || 0) - (a.views || 0));
    return out.slice(0, 10);
  } catch (e) { console.error("[tiktok]", e.message); return []; }
}

async function instagram() {
  try {
    const instatouch = require("instatouch");
    const sess = process.env.IG_SESSION;
    const accounts = (process.env.IG_ACCOUNTS || "minecraft")
      .split(",").map((s) => s.trim()).filter(Boolean);
    const out = [];
    for (const acc of accounts) {
      try {
        const res = await instatouch.user(acc, {
          count: 6, ...(sess ? { session: `sessionid=${sess}` } : {}),
        });
        let n = 0;
        for (const p of (res.collector || [])) {
          const isVid = p.is_video || p.type === "video";
          if (!isVid) continue;
          out.push({
            id: "ig" + (p.shortcode || p.id),
            title: (p.description || p.caption || "(reel)").slice(0, 90),
            url: `https://www.instagram.com/reel/${p.shortcode}/`,
            author: acc,
            views: p.video_view_count || p.playCount || null,
          });
          if (++n >= 2) break;
        }
      } catch (e) { console.error("[ig]", acc, e.message); }
    }
    return out.slice(0, 10);
  } catch (e) { console.error("[instagram]", e.message); return []; }
}

(async () => {
  const data = { tiktok: await tiktok(), instagram: await instagram() };
  fs.writeFileSync("social.json", JSON.stringify(data));
  console.error(`social.json: tiktok=${data.tiktok.length} instagram=${data.instagram.length}`);
})();
