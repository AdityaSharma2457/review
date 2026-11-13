import webbrowser
from urllib.parse import quote

place_id = "ChIJQzrVAnSFbzkRoYGB7gJGIwg"
review_url = f"https://search.google.com/local/writereview?placeid={place_id}"

webbrowser.open(review_url)

