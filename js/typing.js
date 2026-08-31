/* ═══════════════════════════════════════════════
 * typing.js — 台词「打字机」效果
 * 只负责把一段文本逐字显示到对话栏；不含任何播放推进逻辑。
 * 通过回调通知「打完字」事件，交给 streaming.js 决定是否推进。
 * ═══════════════════════════════════════════════ */

const Typing = {
  // 当前打字定时器句柄，用于点击「跳过本句」时清掉
  _timer: null,
  _el: null,
  _text: "",
  _idx: 0,
  _onDone: null,      // 打完全部字后的回调（streaming 用来自动播放续推）
  _onTick: null,      // 每打一个字的可选回调

  /**
   * 开始打字。若上一次没打完就清掉重来。
   * @param {HTMLElement} el   目标元素（对话栏文本容器）
   * @param {string} text      完整台词
   * @param {number} speedMs   每字间隔
   * @param {{onDone:Function, onTick:Function}} callbacks
   */
  start(el, text, speedMs, { onDone, onTick } = {}) {
    this.cancel();
    this._el = el;
    this._text = text;
    this._idx = 0;
    this._onDone = onDone || null;
    this._onTick = onTick || null;
    el.textContent = "";
    this._tick();
  },

  _tick() {
    if (this._idx >= this._text.length) {
      // 打完了
      this._timer = null;
      if (this._onDone) this._onDone();
      return;
    }
    this._idx += 1;
    this._el.textContent = this._text.slice(0, this._idx);
    if (this._onTick) this._onTick(this._idx, this._text.length);
    this._timer = setTimeout(() => this._tick(), Modes.typingSpeed);
  },

  /** 是否仍在打字中 */
  isTyping() {
    return this._timer !== null;
  },

  /**
   * 跳过打字、直接显示完整台词。
   * @returns {boolean} 之前是否正在打字（若在打则现在已跳完）
   */
  skipToEnd() {
    if (this._timer === null) return false;
    this.cancel();
    this._el.textContent = this._text;
    if (this._onDone) this._onDone();
    return true;
  },

  cancel() {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  },
};