# Showrun lesson overlay
# The source trace is immutable. This file controls presentation and pedagogy.

Source "./showrun-session.jsonl"
Title "Could agent sessions become documentation?"
Set Theme "editorial"
Set AspectRatio "16:9"
Set Captions true
Set Speed 1

Chapter "The spark" At 0
Caption "Start with a familiar interaction model."
Note "“VHS for agents” makes the unfamiliar legible. The analogy supplies the **mental model** before the implementation exists."
TeachingPoint "Use a familiar tool as the bridge to a new category."

Chapter "The shortcut" At 24
Caption "Replay is not the same as rerun."
Note "A saved trace can power **deterministic playback** without calling the model or touching external tools again."
TeachingPoint "Separate faithful presentation from behavioral reproduction."
Focus Event 6
Pause 2s

Chapter "The landscape" At 66
Caption "Let adjacency sharpen the idea."
Note "Existing replay products validate the primitive. The missing layer is editorial: pacing, teaching, and documentation-native output."
TeachingPoint "Competition can clarify the missing layer instead of killing the idea."
Highlight Tool "web_research"

Chapter "The wedge" At 88
Caption "The niche changes the product."
Note "Learning material needs chapters, captions, accessibility, stable artifacts, and a repeatable rendering pipeline."
TeachingPoint "A specific audience turns generic replay into a focused product."
Pause 2s

Chapter "The artifact" At 108
Caption "The first lesson explains itself."
Note "This conversation is both the source trace and the subject of the demonstration—a compact proof of the workflow."
TeachingPoint "Dogfooding makes the value legible in a single click."
Assert Event "prototype_created"

Output "showrun-prototype.html"
Output "showrun-prototype.mp4"
