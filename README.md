#
Transcript (Speech To Text API) , Translate (Google Translate API) and Dub (Google TTS API) Videos in languages supported by TTS API.



## Setup:

### 1. Download all install all dependencies 

   ```
   pip install -r requirements.txt
   ```

### 2. Setup GCP 

​	a. Login to your GCP acc. and create a service acc. with Full Access to Translation and Cloud Storage API.

​	b. Enable the TTS STT and Translation API

  	    gcloud services enable texttospeech.googleapis.com translate.googleapis.com speech.googleapis.com 

​	c. Create a storage bucket for temp. storing audio clip. (Make sure your service account has full Access)

```
	gsutil mb gs://blob_name
```



### 3. Configuring Keys and Environment variables

   a. Generate and Download `keys.json` for your service account.

   b. Copy it in the Project Directory

   c. Create `.env` file with the following Env. Variables:

   ```
   PROJECT_ID="your_gcp_project_id"
   STORAGE_BUCKET="blob_name"
   GOOGLE_APPLICATION_CREDENTIALS="keys.json"
   ```

   

### 4. Run `transcryber` with options

   Options:

```
    ytdl : To download YT video.
    dub : To dub video.
```



#### Downloading YouTube Video:

```
    python transcryber ytdl --url https://www.youtube.com/watch?v=video_id
```


        Args:
                url (String): URL link of YouTube Video i.e https://www.youtube.com/watch?v=video_id
                file_name (String, optional): Name of the file , i.e. "video.mp4"
                path (int, optional): File Download Location.
    
        Returns:
                bytes : Video in MP4 format



#### Dubbing Video:

```
	python transcryber dub --videoFile video.mp4 --srcLang "en" --targetLang ["hi","jp"]
```

        Args:
            videoFile (String): File to dub
            outputDir (String): Directory to write output files
            srcLang (String): Language code to translate from (i.e. "en")
            targetLangs (list, optional): Languages to translate too, i.e. ["en", "hi"]
            phraseHints (list, optional): "Hints" for words likely to appear in audio. Defaults to [].
            dubSrc (bool, optional): Whether to generate dubs in the source language. Defaults to False.
            speakerCount (int, optional): How many speakers in the video. Defaults to 1.
            voices (dict, optional): Which voices to use for dubbing, i.e. {"en": "en-AU-Standard-A"}. Defaults to {}.

