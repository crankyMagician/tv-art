# tv-art

Weekly sets of public domain paintings for the home screens of our two Google TVs. A GitHub Action rebuilds them every Monday from the [Met Open Access API](https://metmuseum.github.io/) and publishes them to GitHub Pages.

Each image is a 1920x1080 JPEG with the whole painting centered on a dark mat and a small caption in the corner. The fork of LtvLauncher at [crankyMagician/LtvLauncher](https://github.com/crankyMagician/LtvLauncher) reads a feed and shows one picture a day as the home screen background.

## Feeds

| TV | Theme | Feed |
| --- | --- | --- |
| Downstairs (living room) | Landscapes | https://crankymagician.github.io/tv-art/downstairs/feed.json |
| Upstairs (bedroom) | Impressionists | https://crankymagician.github.io/tv-art/upstairs/feed.json |

`https://crankymagician.github.io/tv-art/index.json` lists all feeds. The launcher reads it to build its feed menu.

## Changing what shows up

Edit `themes.json`. Each feed has a list of Met search queries, and `departmentId` narrows a query to one department (11 is European Paintings, 1 is the American Wing). Only public domain paintings with an image are used. Pushing a change to `themes.json` rebuilds the feeds right away. You can also run the workflow by hand from the Actions tab.

## Run it locally

```
pip install -r requirements.txt
python scripts/build_art.py --out site --count 3
```
