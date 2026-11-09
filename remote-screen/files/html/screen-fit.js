// How big the screen image is drawn. In its own tab it is drawn at twice the panel size (CSS caps
// it to the window). Inside a Fluidd or Mainsail camera tile it fills the tile, keeping the
// panel's proportions, and follows the tile when it is resized or opened full screen.
const STANDALONE_ZOOM = 2;

function screenZoom(isEmbedded, frameSize, panelSize) {
    if (!isEmbedded) return STANDALONE_ZOOM;
    return Math.min(frameSize.width / panelSize.width, frameSize.height / panelSize.height);
}
