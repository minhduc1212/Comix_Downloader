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

# GET METADATA
    h1 class="mpage__title": title
    div class="poster" -> get img
    div: mpage__desc-wrap -> get desc


# TODO
    change webp to jpg
    auto change user agent

# APP
custom tkinter 
    User:   Paste the url of manga, .. you want to download -> click get -> show cover, desc, title
            that area to show chapters of each page in get_chapters, click -> to change the page of chapter list
            download each chapter or the whole manga
            choose path to save
            custom tkinter
            progress bar to know all the progeress image ?/? chapter ?/?
            choose the group to download -> the chapter below only show the group
            show what chapter done

# fix
    Error downloading https://j24n.wowpic1.store/i4/bEqPbYfoMT0Gm03lbmafoBJcyrkdVvw/11.webp: ('Connection broken: IncompleteRead(430724 bytes read, 115324 more expected)', IncompleteRead(430724 bytes read, 115324 more expected)) -> not done -> wait more for loading -> just end if the status is 404