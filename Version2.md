


What is needed?


1. Mimic real browsing to never alert youtube servers that this is a bot
    - Must choose random times for next transcript fetch, space randomly for multiple requests
    - Still poll every 30 minutes for new uploads but span the transcript fetches over that 30 minute window randomly
    - use only yt-dlp ideally, with cookies. (note that ipv6 workaround are not available with my isp)



2. Email alerts stay as core feature, but I want to access the results on my computer in a clear way
    - So that means storing the summaries and transcripts in the database
    - access through web app (or better alternative what are the options for this?)
    - view and interact with any of the previous summaries / transcripts
        - get multiple choice quizzes on the content (uses single shot prompt)



3. Allow for deep dives into a channel. (save for later)
    - Agentic workflow to give an LLM tools to dig into a given channel and all its videos
    - Allow for it to choose maybe 3 videos in a given half hour window to grab transcripts for
    - Work as long as needed until it has a complete picture of summaries from the account
    - Provide the best information condensed down into a document


4. Extra feature since it's much more involved, but extend the agentic workflow into a full AI youtube viewer to act as an extension of myself to watch videos for me
    - provide it a topic in an openclaw type interface / chat
    - it will search for the best videos on the topic, get summaries, then formulate a document of the best information on the topic and report back



5. The features from the original. 
    - Extension to manage what channels are polled, and filters on them
        - Keep as extension since then it can know the context of the page my browser is on so I can just go to a channel and the extension will be able to show a button overlaid on the page to add / remove from watch list
    - Email summaries for these

    - Also the function of the original to right click on a video to get a summary sent right away


6. Intelligent back offs.
    - Listen for youtube blocking requests and immediately back off for ALL requests for a given amount of time (optimzied so that youtube will unblock the ip as soon as possible). Then if it's still not unblocked after that amount of time wait much longer etc -- standard back off







