
   
import pydub
from pydub import AudioSegment #for audio splitting 
from google.cloud import speech_v1p1beta1 as speech #gcp speech synthesis  using stt api
from google.cloud import texttospeech  #for speech synthesis tts api
from google.cloud import translate_v2 as translate  #client for translate api
from google.cloud import storage #gcp blob storage client
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip #for stitching audio and video
from moviepy.video.tools.subtitles import SubtitlesClip, TextClip #for adding subtitle to video 
from pytube import YouTube #lib to download yt videos
from pytube.cli import on_progress #progress bar component 
#banner stuff
from termcolor import cprint #for colored terminal o/p
#env vars
from dotenv import load_dotenv #for accessing .env variables 
load_dotenv()
import os,shutil,ffmpeg,time,json,sys,tempfile,uuid,fire,html #misc


def get_yt_video(url,file_name='video',path=None,srt=False):
    """Download Video from YouTube
    Args:
        file_url (String): URL link of YouTube Video i.e https://www.youtube.com/watch?v=video_id
        file_name (String, optional): Name of the file , i.e. "video.mp4"
        path (int, optional): File Download Location.
        
    Returns:
        bytes : Video in MP4 format
    """
    #downloding video
    yt = YouTube(url,on_progress_callback=on_progress) 
    stream = yt.streams.get_by_itag(22)
    print(f'\n'+ 'Downloading: ', yt.title, 'File Size:',str(round((stream.filesize/1024)/1024,2))+'M')
    stream.download(filename=file_name,output_path=path)

    #generating .srt subtitles
    if srt:
        caption = yt.captions['a.en']
        srt_captions = caption.generate_srt_captions()
        text_file = open("captions.srt", "w")
        text_file.write(srt_captions)
        text_file.close()

def decode_audio(inFile, outFile):
    """Convert a video file to wav file.
    Args:
        inFile (String): i.e. movie.mp4
        outFile (String): i.e. movie.wav
    """
    if not outFile[-4:] != "wav":
        outFile += ".wav"
    AudioSegment.from_file(inFile).set_channels(
        1).export(outFile, format="wav")

def get_transcripts_json(gcsPath, langCode, phraseHints=[], speakerCount=1, enhancedModel=None):
    """Transcribes audio files and formats json file
    Args:
        gcsPath (String): path to file in cloud storage (i.e. "gs://audio/clip.mp4")
        langCode (String): language code ("en-US", see https://cloud.google.com/speech-to-text/docs/languages)
        phraseHints (String[]): list of words that are unusual but likely to appear in the audio file.
        speakerCount (int, optional): Number of speakers in the audio. Only works on English. Defaults to None.
        enhancedModel (String, optional): Option to use an enhanced speech model, i.e. "video"
        \n
    Returns:
        json list | Operation.error
    """

    # function for simplifying Google speech client response
    def _jsonify(result):
        json = []
        #traverses through response object of stt api and generates json in this format
        for section in result.results: 
            data = {
                "transcript": section.alternatives[0].transcript,
                "words": []
            }#start time end time convert from second and nano seconds 
            for word in section.alternatives[0].words:
                data["words"].append({
                    "word": word.word,
                    "start_time": word.start_time.total_seconds(),  
                    "end_time": word.end_time.total_seconds(),
                    "speaker_tag": word.speaker_tag
                })
            json.append(data)
        return json

    client = speech.SpeechClient()  
    audio = speech.RecognitionAudio(uri=gcsPath)
    # diarize to check no of speakers in the video 
    diarize = speakerCount if speakerCount > 1 else False
    #print(f"Diarization: {diarize}")
    diarizationConfig = speech.SpeakerDiarizationConfig(
        enable_speaker_diarization=speakerCount if speakerCount > 1 else False,
    )

    # For English only we can use the optimized video enhanced model 
    if langCode == "en":
        enhancedModel = "video"

    #this is request object config
    config = speech.RecognitionConfig(
        language_code="en-US" if langCode == "en" else langCode,  #source language
        enable_automatic_punctuation=True, #to recognise punctuation like . ! etc
        enable_word_time_offsets=True, #to get start time | end time of words
        speech_contexts=[{  #Provides hints to the speech recognizer to favor specific words and phrases in the results
            "phrases": phraseHints,
            "boost": 15
        }],
        diarization_config=diarizationConfig,
        profanity_filter=True, #prevents bad words
        use_enhanced=True if enhancedModel else False,
        model="video" if enhancedModel else None

    )
    res = client.long_running_recognize(config=config, audio=audio).result()
    # print("raw_response.json")
    # print(res)

    return _jsonify(res)

def parse_sentence_with_speaker(json, lang):
    """Takes json from get_transcripts_json (transcript.json) and breaks it into sentences
    spoken by a single person. Sentence added where 1 second pause 
    Args:
        json (string[]): [{"transcript": "testing", "words": [{"word": "testt", "start_time": 20, "end_time": 21, "speaker_tag: 2}]}]
        lang (string): language code, i.e. "en"
    Returns:
        string[]: [{"sentence": "testing", "speaker": 1, "start_time": 20, "end_time": 21}]
    """

    def get_word(word, lang):
        if lang == "ja": #for japnese language word special case
            return word.split('|')[0]
        return word

    sentences = []
    sentence = {}
    for result in json:
        for i, word in enumerate(result['words']):
            wordText = get_word(word['word'], lang)
            if not sentence:
                sentence = {
                    lang: [wordText],
                    'speaker': word['speaker_tag'],
                    'start_time': word['start_time'],
                    'end_time': word['end_time']
                }
            # if more than one speaker save it to anohter one
            elif word['speaker_tag'] != sentence['speaker']:
                sentence[lang] = ' '.join(sentence[lang])
                sentences.append(sentence)
                sentence = {
                    lang: [wordText],
                    'speaker': word['speaker_tag'],
                    'start_time': word['start_time'],
                    'end_time': word['end_time']
                }
            else:
                sentence[lang].append(wordText)
                sentence['end_time'] = word['end_time']

            # If there's greater than one second gap then its as new sentence
            if i+1 < len(result['words']) and word['end_time'] < result['words'][i+1]['start_time']:
                sentence[lang] = ' '.join(sentence[lang])
                sentences.append(sentence)
                sentence = {}
        if sentence:
            sentence[lang] = ' '.join(sentence[lang])
            sentences.append(sentence)
            sentence = {}

    return sentences

def translate_text(input, targetLang, sourceLang=None):
    """Translates from sourceLang to targetLang. If sourceLang is empty,
    it will be auto-detected.
    Args:
        sentence (String): Senteence to translate
        targetLang (String): i.e. "hi"
        sourceLang (String, optional): i.e. "en" Defaults to None.
    Returns:
        String: translated text
    """

    translate_client = translate.Client()
    #translates each sentence
    result = translate_client.translate(
        input, target_language=targetLang, source_language=sourceLang)
    # print(result['translatedText']))
    return html.unescape(result['translatedText'])

def speak(text, languageCode, voiceName=None, speakingRate=1):
    """Converts text to audio
    Args:
        text (String): Text to be spoken
        languageCode (String): Language (i.e. "en")
        voiceName: (String, optional): See https://cloud.google.com/text-to-speech/docs/voices
        speakingRate: (int, optional): Speaking rate/speed, in the range [0.25, 4.0].
    
    Returns:
        bytes : Audio in wav format
        Helper function of speakUnderDuration function
    """

    client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=text)

    # Build the voice request select the language code ("en-US") and the ssml
    # voice gender ("neutral")
    if not voiceName:
        voice = texttospeech.VoiceSelectionParams(
            language_code=languageCode, ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
        )
    else:
        voice = texttospeech.VoiceSelectionParams(
            language_code=languageCode, name=voiceName
        )

    # Select the type of audio file you want returned
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speakingRate
    )

    # Perform the text-to-speech request on the text input with the selected voice parameters and audio file type
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )

    return response.audio_content

def speakUnderDuration(text, languageCode, durationSecs, voiceName=None):
    """Speak text within a certain time limit.
    If audio alrady fits within durationSecs no changes will be made.
    Args:
        text (String): Text to be spoken
        languageCode (String): language code, i.e. "en"
        durationSecs (int): Time limit in seconds
        voiceName (String, optional): See https://cloud.google.com/text-to-speech/docs/voices
    Returns:
        bytes : Audio in wav format
    
    """
    baseAudio = speak(text, languageCode, voiceName=voiceName)
    assert len(baseAudio)
    #crete a temprorary audio file copy to get the duration or length and check if it fits within durationSecs
    f = tempfile.NamedTemporaryFile(mode="w+b")
    f.write(baseAudio)
    f.flush()
    baseDuration = AudioSegment.from_mp3(f.name).duration_seconds
    f.close()
    ratio = baseDuration / durationSecs

    # if the audio fits, return it
    if ratio <= 1:
        return baseAudio

    # If the base audio is too long to fit in the segment...

    # round to one decimal point and increase speed of the speech
    ratio = round(ratio, 1)
    if ratio > 4:
        ratio = 4
    return speak(text, languageCode, voiceName=voiceName, speakingRate=ratio)

def toSrt(transcripts, charsPerLine=60):
    """Converts transcripts to SRT an SRT file. Only for English
    Args:
        transcripts ({}): Transcripts returned from Speech API
        charsPerLine (int): max number of chars to write per line
    Returns:
        String srt data
    """

    """
    SRT files format:
    [Section of subtitles number]
    [Time the subtitle is displayed begins] –> [Time the subtitle is displayed ends]
    [Subtitle]
    Timestamps are in the format:
    [hours]: [minutes]: [seconds], [milliseconds]
    #60 characters fit on one line
    
    e.g 0:1:23,500 --> 0:1:27,0
             be extremely stressed as a kid. I was a perfectionist very shy.
   
    """

    def _srtTime(seconds):
        millisecs = seconds * 1000
        seconds, millisecs = divmod(millisecs, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return "%d:%d:%d,%d" % (hours, minutes, seconds, millisecs)

    def _toSrt(words, startTime, endTime, index):
        return f"{index}\n" + _srtTime(startTime) + " --> " + _srtTime(endTime) + f"\n{words}"

    startTime = None
    sentence = ""
    srt = []
    index = 1
    for word in [word for x in transcripts for word in x['words']]:
        if not startTime:
            startTime = word['start_time']

        sentence += " " + word['word']

        if len(sentence) > charsPerLine:
            srt.append(_toSrt(sentence, startTime, word['end_time'], index))
            index += 1
            sentence = ""
            startTime = None

    if len(sentence):
        srt.append(_toSrt(sentence, startTime, word['end_time'], index))

    return '\n\n'.join(srt)

def stitch_audio(sentences, audioDir, movieFile, outFile, srtPath=None, overlayGain=-30):
    """Combines sentences, audio clips, and video file into the one dubbed video
    Args:
        sentences (list): Output of parse_sentence_with_speaker
        audioDir (String): Directory containing generated audio files to stitch together
        movieFile (String): Path to video file to dub.
        outFile (String): Where to write dubbed movie.
        srtPath (String, optional): Path to transcript/srt file, if desired.
        overlayGain (int, optional): How quiet to make source audio when overlaying dubs. 
            Defaults to -30.
    Returns:
       void : Writes video file to outFile path
    """
    # srtPath = os.path.abspath(srtPath)

    # Files in the audioDir would be labeled 0.wav, 1.wav, etc.
    audioFiles = os.listdir(audioDir)
    audioFiles.sort(key=lambda x: int(x.split('.')[0]))

    # Grab each audio file
    segments = [AudioSegment.from_mp3(
        os.path.join(audioDir, x)) for x in audioFiles]
    # grab the original audio
    dubbed = AudioSegment.from_file(movieFile)

    # place each audio at the correct timestamp
    for sentence, segment in zip(sentences, segments):
        dubbed = dubbed.overlay(
            segment, position=sentence['start_time'] * 1000, gain_during_overlay=overlayGain)
    # Write  final audio to a temporary output file
    audioFile = tempfile.NamedTemporaryFile()
    dubbed.export(audioFile)
    audioFile.flush()

    # Add the new audio to the video and save it
    clip = VideoFileClip(movieFile)
    audio = AudioFileClip(audioFile.name)
    clip = clip.set_audio(audio)

    # Add subtitles if provided any
    if srtPath:
        # print(srtPath)
        width, height = clip.size[0] * 0.75, clip.size[1] * 0.20
        def generator(txt): 
            # print(txt)
            return TextClip(txt, font='Georgia-Regular',
                                            size=[width, height], color='black', method="caption")
        subtitles = SubtitlesClip(
            srtPath, generator).set_pos(("center", "bottom"))
        clip = CompositeVideoClip([clip, subtitles])

    clip.write_videofile(outFile, codec='libx264',threads=8, audio_codec='aac')
    audioFile.close()

def dub(
        videoFile, outputDir, srcLang, targetLangs,
        storageBucket=None, phraseHints=[], dubSrc=False,
        speakerCount=1, voices={}, srt=False,
        newDir=False, genAudio=False, noTranslate=False):
    """Translate and dub a video.
    Args:
        videoFile (String): File to dub
        outputDir (String): Directory to write output files
        srcLang (String): Language code to translate from (i.e. "en")
        targetLangs (list, optional): Languages to translate too, i.e. ["en", "hi"]
        phraseHints (list, optional): "Hints" for words likely to appear in audio. Defaults to [].
        dubSrc (bool, optional): Whether to generate dubs in the source language. Defaults to False.
        speakerCount (int, optional): How many speakers in the video. Defaults to 1.
        voices (dict, optional): Which voices to use for dubbing, i.e. {"en": "en-AU-Standard-A"}. Defaults to {}.
    The default reequirement is videoFile and targetLangs Ex:
        >>> python3 transcryber --help 
        to get all commands list e.g (i.e ytdl, dub)
        >>> python3 transcryber --flags
        use appropriate flags
    Raises:
        void : Writes dubbed video and intermediate files to outputDir
    
    """

    baseName = os.path.split(videoFile)[-1].split('.')[0]

    #create output dir
    if newDir:
        shutil.rmtree(outputDir)

    if not os.path.exists(outputDir):
        os.mkdir(outputDir)

    outputFiles = os.listdir(outputDir)

    #check if audio is already generated
    if not f"{baseName}.wav" in outputFiles:
        print("⏳ Extracting audio from video...")
        fn = os.path.join(outputDir, baseName + ".wav")
        decode_audio(videoFile, fn) #generate audio file
        # print(f"Wrote {fn}")

    #check for transcript if is alredy generated
    if not f"transcript.json" in outputFiles:
        
        storageBucket =  os.environ['STORAGE_BUCKET']
        if not storageBucket:
            raise Exception(
                "Specify STORAGE_BUCKET in .env or as an arg")
        # print("StorageBucketID:"+storageBucket)
        print("⏳ Transcribing audio...")
        print("⏳ Now Uploading to the cloud storage...")
  
        storage_client = storage.Client()
     
        bucket = storage_client.bucket(storageBucket)

        tmpFile = os.path.join("tmp", str(uuid.uuid4()) + ".wav")
        blob = bucket.blob(tmpFile)
        # blob upload audio file to the cloud
        blob.upload_from_filename(os.path.join(
            outputDir, baseName + ".wav"), content_type="audio/wav")
            
        gcspath = "gs://"+storageBucket+"/"+tmpFile
        # print("Input language:"+srcLang)

        print("⏳ Transcribing... "+tmpFile)
        #generate transcript
        transcripts = get_transcripts_json(gcspath, srcLang,
            phraseHints=phraseHints,
            speakerCount=speakerCount)
        json.dump(transcripts, open(os.path.join(
            outputDir, "transcript.json"), "w"))

        sentences = parse_sentence_with_speaker(transcripts, srcLang)
        fn = os.path.join(outputDir, baseName + ".json")
        with open(fn, "w") as f:
            json.dump(sentences, f)
        print(f"✅ Transcript Wrote {fn}")
        
        blob.delete() #Deleting cloud file...

    srtPath = os.path.join(outputDir, "subtitles.srt") if srt else None
    if srt:
        transcripts = json.load(
            open(os.path.join(outputDir, "transcript.json")))
        subtitles = toSrt(transcripts)
        with open(srtPath, "w") as f:
            f.write(subtitles)
        print(
            f"📝 Wrote srt subtitles to {os.path.join(outputDir, 'subtitles.srt')}")

    sentences = json.load(open(os.path.join(outputDir, baseName + ".json")))
    sentence = sentences[0]

    if not noTranslate:
        for lang in targetLangs:
            print(f"⏳ Translating to {lang}...")
            for sentence in sentences:
                sentence[lang] = translate_text(
                    sentence[srcLang], lang, srcLang)

    
        fn = os.path.join(outputDir, baseName + ".json")     # Write the translations to video_file_name.json
        with open(fn, "w") as f:
            json.dump(sentences, f)
        print("✅ Translation Completed 💯")

    audioDir = os.path.join(outputDir, "audioClips")
    if not "audioClips" in outputFiles:
        os.mkdir(audioDir)

    # whether or not to also dub the source language
    if dubSrc:
        targetLangs += [srcLang]

    #create folder according to language
    for lang in targetLangs:
        languageDir = os.path.join(audioDir, lang)
        if os.path.exists(languageDir):
            if not genAudio:
                continue
            shutil.rmtree(languageDir)
        os.mkdir(languageDir)
        print(f"🔉 Synthesizing audio for {lang}")
        for i, sentence in enumerate(sentences):
            voiceName = voices[lang] if lang in voices else None
            audio = speakUnderDuration(
                sentence[lang], lang, sentence['end_time'] -
                sentence['start_time'],
                voiceName=voiceName)
            #write audio files for each sentence
            with open(os.path.join(languageDir, f"{i}.mp3"), 'wb') as f:
                f.write(audio)

    dubbedDir = os.path.join(outputDir, "dubbedVideos")

    if not "dubbedVideos" in outputFiles:
        os.mkdir(dubbedDir)
    #stitch audio generate final video
    for lang in targetLangs:
        print(f"⏳ Dubbing audio for {lang}...")
        outFile = os.path.join(dubbedDir, lang + ".mp4")
        stitch_audio(sentences, os.path.join(
            audioDir, lang), videoFile, outFile, srtPath=srtPath)

    print("Done ✅")


if __name__ == "__main__":
    pydub.AudioSegment.ffmpeg = "C:\\FFMpeg\\bin\\fmpeg"
    cprint("\n \n➰ ＴＲＡＮＳＣＲＹＢ Ǝ Ｒ ➰ \n \n","blue")

    #fire module allows to pass arguments to python function form command line
    fire.Fire({
        'ytdl':get_yt_video,
        'dub':dub,
    })
