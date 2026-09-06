import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
  siteName: "小蜜蜂影院",
  siteUrl: "https://www.xmfyy.vip"
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

async function init(ext) {
  console.log("初始化爬虫:", appConfig.siteName);
}

var classList = [
  { type_id: "1", type_name: "电影" },
  { type_id: "2", type_name: "连续剧" },
  { type_id: "3", type_name: "综艺" },
  { type_id: "4", type_name: "动漫" }
];

var SUB_CLASS = {
  "1": [["全部", ""], ["动作片", "6"], ["喜剧片", "7"], ["爱情片", "8"], ["科幻片", "9"], ["恐怖片", "10"], ["剧情片", "11"], ["战争片", "12"], ["悬疑片", "21"]],
  "2": [["全部", ""], ["国产剧", "13"], ["港台剧", "14"], ["日韩剧", "15"], ["欧美剧", "16"], ["纪录片", "38"], ["其他剧", "37"]],
  "4": [["全部", ""], ["动漫", "28"], ["番剧", "39"], ["动画片", "19"]]
};

var SORT_FILTER = [["全部", ""], ["最新", "time"], ["人气", "hits"], ["评分", "score"]];

var LANG_FILTER = [
  ["全部", ""], ["国语", "国语"], ["粤语", "粤语"], ["英语", "英语"],
  ["日语", "日语"], ["韩语", "韩语"], ["法语", "法语"], ["德语", "德语"],
  ["闽语", "闽语"], ["其它", "其它"]
];

function buildYearFilter() {
  var cur = new Date().getFullYear();
  var arr = [["全部", ""]];
  for (var y = cur; y >= 2014; y--) arr.push([String(y), String(y)]);
  return arr;
}

var YEAR_FILTER = buildYearFilter();

function toFilterObj(arr) {
  return arr.map(function (g) { return { n: g[0], v: g[1] }; });
}

function buildFilters(tid) {
  return [
    { key: "sub", name: "分类", value: toFilterObj(SUB_CLASS[tid] || [["全部", ""]]) },
    { key: "by", name: "排序", value: toFilterObj(SORT_FILTER) },
    { key: "year", name: "年份", value: toFilterObj(YEAR_FILTER) },
    { key: "lang", name: "语言", value: toFilterObj(LANG_FILTER) }
  ];
}

var myFilters = {};
classList.forEach(function (c) { myFilters[c.type_id] = buildFilters(c.type_id); });

function mergeFilter(extend, filter) {
  var out = Object.assign({}, extend);
  if (Array.isArray(filter)) {
    filter.forEach(function (f) { if (f && typeof f === 'object') Object.assign(out, f); });
  } else if (filter && typeof filter === 'object') {
    Object.assign(out, filter);
  }
  return out;
}
// 筛选路由: /index.php/vod/show/id/{tid}/by/{sort}/year/{year}/lang/{lang}/page/{page}.html
function buildCategoryUrl(tid, pg, filter) {
  var parts = ["/index.php/vod/show/id/" + (filter.sub || tid)];
  if (filter.by) parts.push("by/" + filter.by);
  if (filter.year) parts.push("year/" + filter.year);
  if (filter.lang) parts.push("lang/" + encodeURIComponent(filter.lang));
  parts.push("page/" + (pg || 1));
  return appConfig.siteUrl + parts.join("/") + ".html";
}

// 搜索路由: /index.php/vod/search/page/{page}/wd/{wd}.html
function buildSearchUrl(wd, page) {
  return appConfig.siteUrl + "/index.php/vod/search/page/" + (page || 1) + "/wd/" + encodeURIComponent(wd) + ".html";
}

function normalizePic(src) {
  if (!src) return '';
  if (src.indexOf('//') === 0) return 'https:' + src;
  if (src.indexOf('http') === 0) return src;
  if (src.indexOf('/') === 0) return appConfig.siteUrl + src;
  return appConfig.siteUrl + '/' + src.replace(/^\.?\//, '');
}

async function httpGet(url, referer, minLength) {
  var minLen = (typeof minLength === 'number') ? minLength : 200;
  var headers = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "identity",
    "Referer": referer || (appConfig.siteUrl + '/')
  };
  for (var i = 0; i < 3; i++) {
    try {
      var resp = await req(url, { method: "GET", headers: headers });
      var content = resp.content || '';
      if (typeof content !== 'string') content = String(content);
      if (content.length > minLen) return content;
      await new Promise(function (r) { setTimeout(r, 500); });
    } catch (e) {
      console.error("httpGet失败[" + i + "]:", e.message);
      await new Promise(function (r) { setTimeout(r, 800); });
    }
  }
  return '';
}

function parseVodList(html) {
  var $ = cheerio.load(html);
  var list = [];
  $('a.hl-item-thumb').each(function () {
    var card = $(this);
    var href = card.attr('href') || '';
    var m = href.match(/detail\/id\/(\d+)/);
    if (!m) return;
    var name = (card.attr('title') || '').trim();
    if (!name) return;
    var pic = card.attr('data-original') || '';
    var note = card.find('.hl-pic-text .remarks').first().text().trim();
    if (!note) note = card.find('.remarks').first().text().trim();
    list.push({
      vod_id: m[1],
      vod_name: name,
      vod_pic: normalizePic(pic),
      vod_remarks: note
    });
  });
  var maxPage = 0;
  $('a[href*="/page/"]').each(function () {
    var href = $(this).attr('href') || '';
    var pm = href.match(/\/page\/(\d+)/);
    if (pm) {
      var p = parseInt(pm[1], 10);
      if (!isNaN(p) && p > maxPage) maxPage = p;
    }
  });
  var pagecount = maxPage > 0 ? maxPage : (list.length > 0 ? 1 : 0);
  return { list: list, pagecount: pagecount };
}

async function detail(id) {
  try {
    var detailUrl = id.indexOf('http') === 0 ? id : appConfig.siteUrl + '/index.php/vod/detail/id/' + String(id).replace(/^\//, '') + '.html';
    var html = await httpGet(detailUrl);
    if (!html) return JSON.stringify({ list: [] });
    var $ = cheerio.load(html);

    var vod_name = $('.hl-dc-title').first().text().trim() || $('h1').first().text().trim() || $('h2').first().text().trim();
    if (!vod_name) vod_name = $('title').text().trim().replace(/[-_—《》].*$/, '').trim();

    var pic = $('.hl-dc-pic .hl-item-thumb').attr('data-original') || $('.hl-dc-pic img').attr('data-original') || $('meta[property="og:image"]').attr('content') || '';

    var vod_year = '', vod_area = '', vod_class = '', vod_director = '', vod_actor = '', vod_remarks = '', vod_content = '', vod_lang = '';

    $('.hl-vod-data li').each(function () {
      var li = $(this);
      var label = li.find('em').first().text().trim().replace(/[：:]/, '');
      if (!label) return;
      var val = li.clone().find('em').remove().end().text().replace(/[\s\n\r]+/g, ' ').trim();
      if (label.indexOf('状态') !== -1) vod_remarks = val;
      else if (label.indexOf('主演') !== -1 || label.indexOf('演员') !== -1) vod_actor = val;
      else if (label.indexOf('导演') !== -1) vod_director = val;
      else if (label.indexOf('类型') !== -1) vod_class = val;
      else if (label.indexOf('地区') !== -1 || label.indexOf('国家') !== -1) vod_area = val;
      else if (label.indexOf('年份') !== -1) vod_year = val;
      else if (label.indexOf('语言') !== -1) vod_lang = val;
      else if (label.indexOf('简介') !== -1) vod_content = val;
    });

    if (vod_content) vod_content = vod_content.substring(0, 500);

    var lineNames = [];
    var groupLists = [];
    $('.hl-plays-from .hl-tabs-btn').each(function (idx) {
      var name = $(this).attr('alt') || ('线路' + (idx + 1));
      lineNames.push(name);
      var eps = [];
      var box = $('.hl-tabs-box').eq(idx);
      box.find('.hl-plays-list a').each(function () {
        var h = $(this).attr('href') || '';
        var n = $(this).text().trim();
        if (h && n) eps.push(n + '$' + h);
      });
      groupLists.push(eps);
    });

    if (groupLists.length === 0) {
      $('a[href*="/vod/play/"]').each(function () {
        var h = $(this).attr('href') || '';
        var n = $(this).text().trim();
        if (!h || !n) return;
        var placed = false;
        for (var i = 0; i < groupLists.length; i++) {
          if (groupLists[i].indexOf(n + '$' + h) === -1) continue;
          placed = true; break;
        }
        if (!placed && groupLists.length === 0) {
          lineNames.push('默认线路');
          groupLists.push([]);
        }
        if (groupLists.length > 0) groupLists[0].push(n + '$' + h);
      });
    }

    return JSON.stringify({ list: [{
      vod_id: String(id),
      vod_name: vod_name,
      vod_pic: normalizePic(pic),
      vod_actor: vod_actor,
      vod_director: vod_director,
      vod_area: vod_area,
      vod_year: vod_year,
      vod_class: vod_class,
      vod_remarks: vod_remarks,
      vod_content: vod_content,
      vod_play_from: lineNames.join('$$$'),
      vod_play_url: groupLists.map(function (g) { return g.join('#'); }).join('$$$')
    }] });
  } catch (e) {
    console.error("详情失败:", e.message);
    return JSON.stringify({ list: [] });
  }
}

// 通过站点内置解析器(麒麟播放器)解析平台URL为直链
async function resolvePlatformUrl(platformUrl) {
  try {
    var parserUrl = 'https://svip.qlplayer.cyou/?url=' + encodeURIComponent(platformUrl);
    var html = await httpGet(parserUrl, appConfig.siteUrl + '/', 1000);
    if (!html) return '';

    var tokenMatch = html.match(/apiToken:\s*"([^"]+)"/);
    if (!tokenMatch) return '';
    var token = tokenMatch[1];

    var apiUrl = 'https://svip.qlplayer.cyou/api/resolve.php?token=' + encodeURIComponent(token);
    var apiResp = await httpGet(apiUrl, parserUrl, 10);
    if (!apiResp) return '';

    var data = JSON.parse(apiResp);
    if (data.code === 200 && data.url) {
      return data.url;
    }
    console.error("解析器返回错误:", data.code, data.msg || '');
    return '';
  } catch (e) {
    console.error("解析平台URL失败:", e.message);
    return '';
  }
}

async function play(flag, id, flags) {
  var Header = { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' };
  try {
    var src = String(id || '').trim();
    if (/\.(m3u8|mp4)(\?|$)/i.test(src)) {
      return JSON.stringify({ parse: 0, url: src, header: JSON.stringify(Header) });
    }
    var playUrl = src.indexOf('http') === 0 ? src : appConfig.siteUrl + '/' + src.replace(/^\//, '');
    var html = await httpGet(playUrl);
    if (!html) return JSON.stringify({ parse: 1, header: JSON.stringify(Header), url: playUrl });

    var realUrl = '';
    var pIdx = html.indexOf('player_aaaa');
    if (pIdx !== -1) {
      var eq = html.indexOf('{', pIdx);
      if (eq !== -1) {
        var depth = 0, inStr = false, esc = false, objText = '';
        for (var i = eq; i < html.length; i++) {
          var c = html[i];
          if (inStr) {
            if (esc) esc = false;
            else if (c === '\\') esc = true;
            else if (c === '"') inStr = false;
          } else {
            if (c === '"') inStr = true;
            else if (c === '{') depth++;
            else if (c === '}') { depth--; if (depth === 0) { objText = html.slice(eq, i + 1); break; } }
          }
        }
        if (objText) {
          try {
            var player = JSON.parse(objText);
            var url = player.url || '';
            var encrypt = player.encrypt || 0;
            if (url) {
              if (encrypt === 1) { try { url = atob(url); } catch (e) {} }
              else if (encrypt === 2) { try { url = decodeURIComponent(atob(url)); } catch (e) { try { url = atob(url); } catch (e2) {} } }
              realUrl = url;
            }
          } catch (e) { console.error("解析player_aaaa失败:", e.message); }
        }
      }
    }

    if (!realUrl) {
      var m3 = html.match(/(https?:\/\/[^\s"'<>]+?\.(m3u8|mp4)[^\s"'<>]*)/);
      if (m3) realUrl = m3[1].replace(/\\\//g, '/');
    }

    // 直链(m3u8/mp4)直接播放
    if (realUrl && /\.(m3u8|mp4)(\?|$)/i.test(realUrl)) {
      return JSON.stringify({ parse: 0, url: realUrl, header: JSON.stringify(Header) });
    }
    // 非直链(视频平台网页链接)通过站点内置解析器获取直链
    if (realUrl && /^https?:\/\//i.test(realUrl)) {
      var resolvedUrl = await resolvePlatformUrl(realUrl);
      if (resolvedUrl) {
        return JSON.stringify({ parse: 0, url: resolvedUrl, header: JSON.stringify(Header) });
      }
      // 解析器失败，交给TVBox解析
      return JSON.stringify({ parse: 1, url: realUrl, header: JSON.stringify(Header) });
    }
    return JSON.stringify({ parse: 1, header: JSON.stringify(Header), url: playUrl });
  } catch (e) {
    console.error("播放失败:", e.message);
    return JSON.stringify({ parse: 1, header: JSON.stringify(Header), url: String(id || '') });
  }
}

async function home(filter) {
  var list = [];
  try {
    var html = await httpGet(appConfig.siteUrl + '/');
    list = parseVodList(html).list.slice(0, 30);
  } catch (e) {
    console.error("首页失败:", e.message);
  }
  return JSON.stringify({ class: classList, filters: myFilters, list: list });
}

async function category(tid, pg, filter, extend) {
  try {
    var merged = mergeFilter(extend || {}, filter);
    var url = buildCategoryUrl(tid, pg || 1, merged);
    var html = await httpGet(url);
    var r = parseVodList(html);
    return JSON.stringify({ list: r.list, pagecount: r.pagecount });
  } catch (e) {
    console.error("分类失败:", e.message);
    return JSON.stringify({ list: [], pagecount: 0 });
  }
}

async function search(wd, quick, page) {
  try {
    var kw = String(wd || '').trim();
    if (!kw) return JSON.stringify({ list: [], pagecount: 0 });
    var url = buildSearchUrl(kw, page || 1);
    var html = await httpGet(url);
    if (!html) return JSON.stringify({ list: [], pagecount: 0 });
    var r = parseVodList(html);
    return JSON.stringify({ list: r.list, pagecount: r.pagecount });
  } catch (e) {
    console.error("搜索失败:", e.message);
    return JSON.stringify({ list: [], pagecount: 0 });
  }
}

export default { init: init, home: home, category: category, detail: detail, search: search, play: play };
