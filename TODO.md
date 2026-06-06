# Plan
    referer = https://comix.to/
    https://jloo.wowpic1.store/i/bEqPbYfoNT0GmkHkQj6fsAJYwq0Za/01.webp -> increase the num of pic to get all pics
    
# GET CHAPTER
    ul class: mchap-list
    li class: mchap-item
    a href
    chapter_url = comix.to + a

    chapter_name = mchap-row__ch + mchap-row__title

    group = mchap-row__group

    repeate the chapters page: start with ?page=1, crawl until not chapter to get

    result {
        "chapter_name"="",
        "chapter_url"="",
        "group"=""
    }

# TODO
    change webp to jpg
    auto change user agent