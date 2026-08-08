import cheerio from 'assets://js/lib/cheerio.min.js';
const appConfig={siteName:"电影人生",siteUrl:"https://dyrs6.vip"};
const UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

// ★★★ 请将下面的 url 改为您浏览器中实际分类路径 ★★★
const classList=[
  {type_id:"dianying",type_name:"电影",url:"/dianying.html"},
  {type_id:"dianshiju",type_name:"电视剧",url:"/dianshiju.html"},
  {type_id:"zongyi",type_name:"综艺",url:"/zongyi.html"},
  {type_id:"dongman",type_name:"动漫",url:"/dongman.html"},
  {type_id:"duanju",type_name:"短剧",url:"/duanju.html"}
];

function getAreaFilter(){return{key:"area",name:"地区",value:[{n:"全部",v:""},{n:"大陆",v:"大陆"},{n:"香港",v:"香港"},{n:"台湾",v:"台湾"},{n:"美国",v:"美国"},{n:"日本",v:"日本"},{n:"韩国",v:"韩国"},{n:"英国",v:"英国"},{n:"法国",v:"法国"},{n:"德国",v:"德国"},{n:"泰国",v:"泰国"},{n:"印度",v:"印度"},{n:"其他",v:"其他"}]};}
function getYearFilter(){let y=[{n:"全部",v:""}];for(let i=new Date().getFullYear();i>=2010;i--)y.push({n:String(i),v:String(i)});return{key:"year",name:"年份",value:y};}
function getLangFilter(){return{key:"lang",name:"语言",value:[{n:"全部",v:""},{n:"国语",v:"国语"},{n:"粤语",v:"粤语"},{n:"英语",v:"英语"},{n:"日语",v:"日语"},{n:"韩语",v:"韩语"},{n:"其他",v:"其他"}]};}
function getTypeFilter(){return{key:"type",name:"类型",value:[{n:"全部",v:""},{n:"剧情",v:"剧情"},{n:"喜剧",v:"喜剧"},{n:"动作",v:"动作"},{n:"爱情",v:"爱情"},{n:"科幻",v:"科幻"},{n:"恐怖",v:"恐怖"},{n:"悬疑",v:"悬疑"},{n:"犯罪",v:"犯罪"},{n:"动画",v:"动画"},{n:"冒险",v:"冒险"},{n:"奇幻",v:"奇幻"},{n:"战争",v:"战争"},{n:"纪录片",v:"纪录片"}]};}
const commonFilters=[getAreaFilter(),getYearFilter(),getLangFilter(),getTypeFilter()];
const myFilters={};classList.forEach(i=>myFilters[i.type_id]=commonFilters);

function fixUrl(u){if(!u)return '';if(u.startsWith('http'))return u;if(u.startsWith('//'))return 'https:'+u;if(u.startsWith('/'))return appConfig.siteUrl+u;return u;}

function parseListHtml(html){
  const $=cheerio.load(html);let list=[],seen={};
  $("a").each(function(){
    let href=$(this).attr("href");if(!href||seen[href])return;
    if(href.startsWith('#')||href.startsWith('javascript:')||href==='/')return;
    if(!href.match(/\/(wzzy|vod|detail|play|movie|video|list|type|category|show|view)\//i)&&!href.match(/\.html$/))return;
    let name=$(this).attr("title")||$(this).text().trim();if(!name||name.length<2)return;
    let hasImg=$(this).find("img").length>0;if(!hasImg){let p=$(this).closest('div,li,a');if(p.find("img").length===0)return;}
    let pic=$(this).find("img").attr("data-original")||$(this).find("img").attr("src")||"";
    if(!pic){let p=$(this).closest('div,li');pic=p.find("img").attr("data-original")||p.find("img").attr("src")||"";}
    seen[href]=true;list.push({vod_id:href,vod_name:name,vod_pic:fixUrl(pic),vod_remarks:""});
  });
  if(list.length===0){
    $("a[href$='.html']").each(function(){
      let href=$(this).attr("href");if(!href||seen[href])return;if(href==='/index.html'||href==='/')return;
      let name=$(this).attr("title")||$(this).text().trim();if(!name||name.length<2)return;
      let hasImg=$(this).find("img").length>0||$(this).closest('div').find("img").length>0;if(!hasImg)return;
      let pic=$(this).find("img").attr("data-original")||$(this).find("img").attr("src")||"";
      if(!pic)pic=$(this).closest('div').find("img").attr("src")||"";
      seen[href]=true;list.push({vod_id:href,vod_name:name,vod_pic:fixUrl(pic),vod_remarks:""});
    });
  }
  let pagecount=1;
  $("a[href*='page=']").each(function(){let m=$(this).attr("href").match(/page=(\d+)/);if(m){let p=parseInt(m[1]);if(p>pagecount)pagecount=p;}});
  if(pagecount===1&&list.length>0&&$("a:contains('下一页'),a:contains('Next'),.page-next").length>0)pagecount=999;
  return{list,pagecount};
}

async function fetchAndParse(url){
  console.log("[电影人生] 请求:",url);
  try{
    let resp=await req(url,{method:"GET",headers:{"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Referer":appConfig.siteUrl}});
    let html=resp.content||"";console.log("[电影人生] 响应长度:",html.length);
    if(!html)return{list:[],pagecount:0};
    let result=parseListHtml(html);console.log("[电影人生] 解析条目:",result.list.length);return result;
  }catch(e){console.error("[电影人生] 请求异常:",e.message);return{list:[],pagecount:0};}
}

async function home(filter){
  let list=[];
  try{
    let html=(await req(appConfig.siteUrl,{method:"GET",headers:{"User-Agent":UA,"Accept":"text/html"}})).content||"";
    let result=parseListHtml(html);list=result.list.slice(0,30);
  }catch(e){console.error("首页失败:",e.message);}
  return JSON.stringify({class:classList,filters:myFilters,list});
}

async function category(tid,pg,filter,extend){
  pg=pg||1;extend=extend||{};
  let cat=classList.find(c=>c.type_id===tid);if(!cat)return JSON.stringify({list:[],pagecount:0,page:pg,limit:20,total:0});
  let [path,query]=cat.url.split('?');let params=new URLSearchParams(query||'');
  if(extend.area)params.set('area',extend.area);if(extend.year)params.set('year',extend.year);
  if(extend.lang)params.set('lang',extend.lang);if(extend.type)params.set('type',extend.type);
  if(pg>1)params.set('page',pg);
  let url=path+(params.toString()?'?'+params.toString():'');
  let fullUrl=appConfig.siteUrl+url;
  let result=await fetchAndParse(fullUrl);
  if(result.list.length===0){console.warn("[电影人生] 分类无数据，回退首页");let h=await fetchAndParse(appConfig.siteUrl);result.list=h.list.slice(0,30);result.pagecount=1;}
  result.page=pg;result.limit=20;result.total=result.pagecount*result.limit;
  return JSON.stringify(result);
}

async function search(wd,quick,page){
  page=page||1;
  try{
    let url=appConfig.siteUrl+"/s.html?name="+encodeURIComponent(wd);if(page>1)url+="&page="+page;
    let result=await fetchAndParse(url);result.page=page;result.limit=20;result.total=result.pagecount*result.limit;
    return JSON.stringify(result);
  }catch(e){return JSON.stringify({list:[],pagecount:0,page,limit:20,total:0});}
}

// ========== 完整详情 ==========
async function detail(id){
  try{
    let html=(await req(appConfig.siteUrl+id,{method:"GET",headers:{"User-Agent":UA,"Accept":"text/html","Referer":appConfig.siteUrl}})).content||"";
    const $=cheerio.load(html);
    let vod_name="",vod_director="",vod_actor="",vod_year="",vod_area="",vod_class="",vod_content="",vod_pic="";
    let hash=id.match(/\/wzzy-\d+\/([a-f0-9]+)\.html/)?.[1]||"";
    vod_pic=hash?appConfig.siteUrl+"/img/id/"+hash+".jpg":"";
    $('script[type="application/ld+json"]').each(function(){try{let d=JSON.parse($(this).html());if(d){if(d.name)vod_name=d.name;if(d.year)vod_year=String(d.year);if(d.countryOfOrigin)vod_area=d.countryOfOrigin;if(d.inLanguage)vod_class=d.inLanguage;if(d.description)vod_content=d.description.replace(/<br \/>/g,"\n").replace(/　/g,"").trim();if(d.director&&d.director.name)vod_director=d.director.name;if(d.actor&&Array.isArray(d.actor))vod_actor=d.actor.map(a=>a.name).filter(Boolean).join(',');}}catch(e){}});
    if(!vod_name)vod_name=$("title").text().replace(/《|》/g,"").replace(/-.*$/,"").trim()||"";
    if(!vod_actor){let desc=$('meta[name="description"]').attr("content")||"";let m=desc.match(/主演包括([^。]+)/);if(m)vod_actor=m[1].trim();}
    if(!vod_director){$("p,div,span").each(function(){let t=$(this).text();if(t.includes("导演")&&!vod_director){let m=t.match(/导演[：:]\s*([^\n\r]+)/);if(m)vod_director=m[1].trim().split(/[,，、\s]/)[0];}});}
    if(!vod_class){$("a[href*='class=']").each(function(){let h=$(this).attr("href")||"";if(h.includes("class=")&&!h.includes("sso")){let m=h.match(/class=([^&]+)/);if(m&&!vod_class)vod_class=decodeURIComponent(m[1]);}});}
    let vod_remarks="";
    // 播放线路
    let lines=[],playlists=[],originEpisodes={};
    $("#episodeContent a[href]").each(function(){let href=$(this).attr("href")||"",name=$(this).attr("data-title")||$(this).text().trim()||"",origin=$(this).attr("data-origin")||"";if(href&&name&&origin){let p=href.match(/[?&]p=(\d+)/);p=p?parseInt(p[1]):0;if(!originEpisodes[origin])originEpisodes[origin]=[];originEpisodes[origin].push({name,href,p});}});
    let originOrder=[];$("[id$='Tab'][data-origin]").each(function(){let o=$(this).attr("data-origin");if(o&&!originOrder.includes(o))originOrder.push(o);});
    if(originOrder.length===0)originOrder=Object.keys(originEpisodes);
    let templateOrigin=Object.keys(originEpisodes)[0];let templateEpisodes=templateOrigin?originEpisodes[templateOrigin]:[];
    originOrder.forEach(origin=>{let eps=originEpisodes[origin];if(!eps||eps.length===0){if(templateEpisodes.length===0)return;eps=templateEpisodes.map(ep=>{let newHref=ep.href.replace(/origin=[^&]+/,'origin='+encodeURIComponent(origin));return{name:ep.name,href:newHref,p:ep.p};});}
    eps.sort((a,b)=>a.p-b.p);let lineEpisodes=eps.map(ep=>ep.name+"$"+ep.href);lines.push(origin);playlists.push(lineEpisodes);});
    if(lines.length===0){lines.push("默认");playlists.push(["暂无播放地址$"+id]);}
    let vod_play_from=lines.filter(Boolean).join("$$$");
    let vod_play_url=playlists.map(eps=>eps.join("#")).join("$$$");
    return JSON.stringify({list:[{vod_id:id,vod_name,vod_pic,vod_actor,vod_director,vod_remarks,vod_year,vod_area,vod_content,vod_class,vod_play_from,vod_play_url}]});
  }catch(e){console.error("详情异常:",e);return JSON.stringify({list:[]});}
}

// ========== 完整播放（含解密） ==========
async function play(flag,id,flags){
  try{
    if(id.startsWith("http"))return JSON.stringify({parse:0,Header:{"User-Agent":UA,"Referer":appConfig.siteUrl},url:id});
    let html=(await req(appConfig.siteUrl+id,{method:"GET",headers:{"User-Agent":UA,"Accept":"text/html","Referer":appConfig.siteUrl}})).content||"";
    // player_aaaa解密
    let ps=html.match(/var\s+player_aaaa\s*=\s*(\{[\s\S]+?\})\s*<\/script>/);
    if(ps){try{let d=JSON.parse(ps[1]);let enc=d.encrypt||0,u=d.url||"";if(u){if(enc===2)u=atob(u);if(enc===1)u=decodeURIComponent(u);if(u.startsWith('http'))return JSON.stringify({parse:0,Header:{"User-Agent":UA,"Referer":appConfig.siteUrl},url:u});}}catch(e){}}
    // /api/m3u8
    let m3=html.match(/href="\/api\/m3u8\?origin=([^&]+)&amp;?url=([^"]+)"/)||html.match(/href="\/api\/m3u8\?origin=([^&]+)&url=([^"]+)"/);
    if(m3){let u=appConfig.siteUrl+"/api/m3u8?origin="+encodeURIComponent(m3[1])+"&url="+m3[2];return JSON.stringify({parse:0,Header:{"User-Agent":UA,"Referer":appConfig.siteUrl},url:u});}
    // 直链
    let um=html.match(/"url"\s*[:=]\s*"([^"]+\.(m3u8|mp4|flv)[^"]*)"/);
    if(um)return JSON.stringify({parse:0,Header:{"User-Agent":UA,"Referer":appConfig.siteUrl},url:um[1].replace(/\\/g,'')});
    // iframe
    const $=cheerio.load(html);let ifs=$("iframe").attr("src");if(ifs)return JSON.stringify({parse:1,Header:{"User-Agent":UA,"Referer":appConfig.siteUrl},url:fixUrl(ifs)});
    let vs=$("video").attr("src");if(vs)return JSON.stringify({parse:0,Header:{"User-Agent":UA,"Referer":appConfig.siteUrl},url:fixUrl(vs)});
    return JSON.stringify({parse:1,Header:{"User-Agent":UA,"Referer":appConfig.siteUrl},url:appConfig.siteUrl+id});
  }catch(e){return JSON.stringify({parse:0,url:""});}
}

async function init(ext){console.log("[电影人生] 初始化，分类:",classList.map(c=>c.type_name+"→"+c.url).join(", "));}
export default{init,home,category,search,detail,play};