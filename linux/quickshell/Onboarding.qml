// Svara voice onboarding: an ordinary window built from the island's own parts — liquid glass over the
// wallpaper (Glass.qml, the compositor's blur frosts the transparent window), a liquid disc that fills as the
// style block is read (LiquidShape.qml), the radial visualiser breathing with your voice (RadialViz.qml).
// Driven by $XDG_RUNTIME_DIR/svara-island.json, the file the pill reads: state "prompt" | "complete",
// text = the line to read, next = the line after it, last = the line just saved, hint = how to read this
// block, styles = [{label, done, total}], style_index, done/total, minutes, bands (five voice levels), key.
// The compositor's hotkey does the recording; this window shows what to read and lets you skip or pause.
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io

FloatingWindow {
    id: page
    required property var dict          // win.dict from shell.qml
    readonly property bool prompting: dict.state === "prompt"
    readonly property bool complete: dict.state === "complete"
    readonly property bool narrow: width < 820
    visible: prompting || complete
    title: "Svara — voice onboarding"
    implicitWidth: 1000
    implicitHeight: 520
    minimumSize: Qt.size(640, 420)
    color: "transparent"
    // closed from the window itself (title bar, Super+Q, the dock): pause the session so Svara agrees.
    // Checked a beat later: a Quickshell config reload also hides the window, but it destroys this
    // component with it, so the timer never fires and the session survives the reload.
    onVisibleChanged: if (!visible && prompting) closeCheck.restart()
    Timer { id: closeCheck; interval: 400; onTriggered: if (!page.visible && page.prompting) page.send("onboard") }

    FontLoader { id: serif; source: Quickshell.shellDir + "/Newsreader.ttf" }   // copy assets/Newsreader.ttf next to shell.qml
    readonly property string serifName: serif.status === FontLoader.Ready ? serif.name : "serif"

    readonly property string fifo: Quickshell.env("XDG_RUNTIME_DIR") + "/svara-hotkey.fifo"
    function send(tok) { Quickshell.execDetached(["sh", "-c", "timeout 1 sh -c 'echo " + tok + " > \"" + fifo + "\"'"]); }

    readonly property var styles: Array.isArray(dict.styles) ? dict.styles : []
    readonly property int cur: Number(dict.style_index) || 0
    readonly property var style: styles[cur] || ({ label: "", done: 0, total: 60 })
    readonly property var bands: Array.isArray(dict.bands) ? dict.bands : []
    readonly property real voice: bands.length ? Math.min(1, Math.max.apply(null, bands) * 1.6) : 0
    readonly property string keyName: String(dict.key || "").indexOf("f23") >= 0 ? "Copilot key" : (dict.key || "dictation key")
    // the five live bands spread into the ring's 28 half-steps, bass at the top
    readonly property var ringBars: {
        const out = [];
        for (let i = 0; i < 28; i++) {
            if (!bands.length) { out.push(0); continue; }
            const t = i / 27 * (bands.length - 1), a = Math.floor(t), b = Math.min(bands.length - 1, a + 1), f = t - a;
            out.push(Math.min(1, (bands[a] * (1 - f) + bands[b] * f) * 1.8));
        }
        return out;
    }

    Glass { anchors.fill: parent; radius: 10 }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: page.narrow ? 30 : 44
        spacing: 0

        // the seven ways to read, as chips; the one being read is lit, finished ones are green
        Flow {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: page.styles.length
                Rectangle {
                    required property int index
                    readonly property var st: page.styles[index] || ({ label: "", done: 0, total: 1 })
                    readonly property bool isNow: index === page.cur && !page.complete
                    readonly property bool isDone: st.done >= st.total
                    height: 28; radius: 14
                    width: chip.implicitWidth + 22
                    color: isNow ? Qt.alpha(Theme.fg, 0.14) : Qt.alpha(Theme.fg, 0.05)
                    border.width: 1; border.color: isNow ? Qt.alpha(Theme.fg, 0.22) : Qt.alpha(Theme.fg, 0.06)
                    Behavior on color { ColorAnimation { duration: 340 } }
                    Row {
                        id: chip
                        anchors.centerIn: parent
                        spacing: 7
                        Text { visible: isDone; text: "\u{EA5E}"; font.family: "noctalia-tabler-icons"; font.pixelSize: 13
                               color: Theme.tertiary; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: st.label; font.family: "Inter"; font.pixelSize: 13
                               font.weight: isNow ? Font.DemiBold : Font.Normal
                               color: isDone ? Theme.tertiary : isNow ? Theme.fg : Theme.dim
                               anchors.verticalCenter: parent.verticalCenter }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }

        // the disc and the line
        RowLayout {
            Layout.fillWidth: true
            spacing: page.narrow ? 28 : 44

            Item {   // the disc: liquid rises as this style's lines are read; the ring is your voice
                Layout.preferredWidth: page.narrow ? 150 : 190
                Layout.preferredHeight: Layout.preferredWidth
                Layout.alignment: Qt.AlignVCenter
                RadialViz {
                    anchors.fill: parent
                    bars: page.ringBars
                    playing: page.voice > 0.03
                    maxLen: 16; gap: 8; count: 56
                }
                Item {
                    anchors.centerIn: parent
                    width: parent.width - 2 * (16 + 8 + 10); height: width
                    LiquidShape {
                        anchors.fill: parent
                        level: page.complete ? 1 : page.style.total ? page.style.done / page.style.total : 0
                        amp: 0.05 + 0.06 * page.voice
                        lobes: 5; lobes2: 7
                    }
                    Text {   // how far through this style
                        anchors.centerIn: parent
                        text: page.complete ? "\u{EA5E}" : (page.style.done + 1) + " / " + page.style.total
                        font.family: page.complete ? "noctalia-tabler-icons" : "Inter"
                        font.pixelSize: page.complete ? 34 : 17; font.weight: Font.DemiBold
                        color: Theme.fg
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Text {
                    Layout.fillWidth: true
                    text: page.complete ? "Every line is recorded." : (page.dict.hint || "Read the line.")
                    font.family: "Inter"; font.pixelSize: 15; color: Theme.dim; wrapMode: Text.Wrap
                }
                // the teleprompter: the line you just read lifts away in green, the next rises into its place
                Item {
                    id: stack
                    Layout.fillWidth: true
                    Layout.topMargin: 12
                    implicitHeight: line.implicitHeight + (nextLine.visible ? nextLine.implicitHeight + 14 : 0)
                    readonly property int big: page.narrow ? 34 : 46
                    Text {
                        id: gone
                        width: parent.width
                        text: page.dict.last || ""
                        font.family: page.serifName; font.pixelSize: stack.big; lineHeight: 1.12
                        color: Theme.tertiary; wrapMode: Text.Wrap; opacity: 0
                        transform: Translate { id: goneLift }
                    }
                    Text {
                        id: line
                        width: parent.width
                        text: page.complete ? "That's all of it." : (page.dict.text || "")
                        font.family: page.serifName; font.pixelSize: stack.big; lineHeight: 1.12
                        color: Theme.fg; wrapMode: Text.Wrap
                        onTextChanged: if (page.dict.last) arrive.restart()
                        transform: Translate { id: lift }
                    }
                    Text {
                        id: nextLine
                        width: parent.width
                        y: line.implicitHeight + 14
                        visible: page.prompting && !!page.dict.next
                        text: page.dict.next || ""
                        font.family: page.serifName; font.pixelSize: page.narrow ? 18 : 21; lineHeight: 1.2
                        color: Qt.alpha(Theme.fg, 0.38); wrapMode: Text.Wrap
                        maximumLineCount: 2; elide: Text.ElideRight
                    }
                    ParallelAnimation {
                        id: arrive
                        SequentialAnimation {
                            PropertyAction { target: gone; property: "opacity"; value: 0.9 }
                            PropertyAction { target: goneLift; property: "y"; value: 0 }
                            ParallelAnimation {
                                NumberAnimation { target: gone; property: "opacity"; to: 0; duration: 420; easing.type: Easing.InQuad }
                                NumberAnimation { target: goneLift; property: "y"; to: -28; duration: 420; easing.type: Easing.OutCubic }
                            }
                        }
                        SequentialAnimation {
                            PropertyAction { target: line; property: "opacity"; value: 0 }
                            PropertyAction { target: lift; property: "y"; value: 26 }
                            PauseAnimation { duration: 90 }
                            ParallelAnimation {
                                NumberAnimation { target: line; property: "opacity"; to: 1; duration: 260; easing.type: Easing.OutCubic }
                                NumberAnimation { target: lift; property: "y"; to: 0; duration: 340; easing.type: Easing.OutCubic }
                            }
                        }
                    }
                }
                Text {   // the mic heard something else: the line stays
                    Layout.topMargin: 10
                    visible: page.prompting && !!page.dict.retry
                    text: "That didn't sound like the line. Once more?"
                    font.family: "Inter"; font.pixelSize: 14; color: Theme.error
                }
                RowLayout {   // the finish: what you gave it
                    Layout.topMargin: 18
                    visible: page.complete
                    spacing: 28
                    Repeater {
                        model: [{ n: String(Number(page.dict.total) || 0), l: "lines" },
                                { n: String(Number(page.dict.minutes) || 0), l: "minutes of your voice" },
                                { n: String(page.styles.length || 7), l: "ways of speaking" }]
                        Column {
                            required property var modelData
                            spacing: 2
                            Text { text: modelData.n; font.family: "Inter"; font.pixelSize: 28; font.weight: Font.Light; color: Theme.fg }
                            Text { text: modelData.l; font.family: "Inter"; font.pixelSize: 13; color: Theme.dim }
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }

        RowLayout {   // the instruction and the two actions
            Layout.fillWidth: true
            spacing: 14
            Text {
                Layout.fillWidth: true
                text: page.complete ? "Svara can now measure itself on your voice and learn your words: run bench/voice_measure.py."
                                    : "Just read the line. A short pause saves it and brings the next one."
                font.family: "Inter"; font.pixelSize: 14; color: Theme.fg; wrapMode: Text.Wrap
            }
            Rectangle {
                visible: page.prompting
                implicitWidth: skipLabel.implicitWidth + 30; implicitHeight: 36; radius: 18
                color: skipHover.hovered ? Qt.alpha(Theme.fg, 0.14) : Qt.alpha(Theme.fg, 0.07)
                Text { id: skipLabel; anchors.centerIn: parent; text: "Skip"; font.family: "Inter"; font.pixelSize: 14; color: Theme.fg }
                HoverHandler { id: skipHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: page.send("skip") }
            }
            Rectangle {
                visible: page.prompting
                implicitWidth: pauseLabel.implicitWidth + 32; implicitHeight: 36; radius: 18
                color: pauseHover.hovered ? Theme.fg : Qt.alpha(Theme.fg, 0.9)
                Text { id: pauseLabel; anchors.centerIn: parent; text: "Pause"
                       font.family: "Inter"; font.pixelSize: 14; font.weight: Font.DemiBold; color: Theme.base }
                HoverHandler { id: pauseHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: page.send("onboard") }
            }
        }
    }
}
