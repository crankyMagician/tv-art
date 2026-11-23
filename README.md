# tv-art

Weekly sets of public domain paintings for the home screens of our two Google TVs. A GitHub Action rebuilds them every Monday from the [Met Open Access API](https://metmuseum.github.io/) and publishes them to GitHub Pages.

Each image is a 1920x1080 JPEG with the whole painting centered on a dark mat and a small caption in the corner. The fork of LtvLauncher at [crankyMagician/LtvLauncher](https://github.com/crankyMagician/LtvLauncher) reads a feed and shows one picture a day as the home screen background.

## Feeds

| TV | Theme | Feed |
| --- | --- | --- |
| Downstairs (living room) | Landscapes | https://crankymagician.github.io/tv-art/downstairs/feed.json |
| Upstairs (bedroom) | Impressionists | https://crankymagician.github.io/tv-art/upstairs/feed.json |

A third feed fills a picture frame on our household mirror: https://crankymagician.github.io/tv-art/mirror/feed.json. It has 40 paintings a week, mixed from the European Paintings, American Wing and Asian Art departments. Because the feed has a `frame` in `themes.json`, each picture is the painting on plain black with its caption underneath, at most 1000 pixels on a side, in place of the 1920x1080 TV mat.

`https://crankymagician.github.io/tv-art/index.json` lists all feeds. The launcher reads it to build its feed menu.

## Changing what shows up

Edit `themes.json`. A feed can set its own `count`. A feed with broad queries should set `searchPages`, the number of result pages read at random per query beyond the first: reading every page of a query such as "painting" takes dozens of requests, and the Met turns a build away when it asks too fast. Each feed has a list of Met search queries, and `departmentId` narrows a query to one department (11 is European Paintings, 1 is the American Wing). Only public domain paintings with an image are used. Pushing a change to `themes.json` rebuilds the feeds right away. You can also run the workflow by hand from the Actions tab.

## Run it locally

```
pip install -r requirements.txt
python scripts/build_art.py --out site --count 3
```

## When the Met refuses a build

Requests are spaced a quarter of a second apart, and a refusal (403 or 429) is followed by a long wait before the next try. A feed that still cannot be built keeps the set that is published now, and the workflow run carries a warning naming it. The run fails only when a feed cannot be built and has nothing published to keep, or when no feed could be built at all.
