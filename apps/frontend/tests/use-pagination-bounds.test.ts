import { describe, expect, it } from 'vitest';
import { collectUnbreakableBounds } from '@/components/preview/use-pagination';

interface Rect {
  top: number;
  bottom: number;
}

function stubRects(el: Element, rect: Rect): void {
  el.getBoundingClientRect = () =>
    ({
      top: rect.top,
      bottom: rect.bottom,
      left: 0,
      right: 0,
      width: 0,
      height: 0,
      x: 0,
      y: 0,
    }) as DOMRect;
}

function buildSwissDom(): {
  container: HTMLElement;
  item: HTMLElement;
  title: HTMLElement;
  bullets: HTMLElement[];
} {
  document.body.innerHTML = `
    <div class="resume-body resume-template-swiss-single">
      <div class="resume-section">
        <h3 class="resume-section-title">项目经历</h3>
        <div class="resume-items">
          <div class="resume-item">
            <div class="entry-header">项目名</div>
            <div class="entry-role">核心开发</div>
            <ul>
              <li>bullet 1</li>
              <li>bullet 2</li>
              <li>bullet 3</li>
            </ul>
          </div>
        </div>
      </div>
    </div>`;
  const container = document.querySelector('.resume-body') as HTMLElement;
  const section = document.querySelector('.resume-section') as HTMLElement;
  const title = section.querySelector('.resume-section-title') as HTMLElement;
  const item = section.querySelector('.resume-item') as HTMLElement;
  const bullets = Array.from(section.querySelectorAll('li')) as HTMLElement[];

  stubRects(container, { top: 0, bottom: 1000 });
  stubRects(section, { top: 100, bottom: 500 });
  stubRects(title, { top: 100, bottom: 130 });
  stubRects(item, { top: 140, bottom: 500 });
  stubRects(section.querySelector('.entry-header') as HTMLElement, { top: 140, bottom: 165 });
  stubRects(section.querySelector('.entry-role') as HTMLElement, { top: 165, bottom: 185 });
  stubRects(bullets[0], { top: 185, bottom: 250 });
  stubRects(bullets[1], { top: 250, bottom: 340 });
  stubRects(bullets[2], { top: 340, bottom: 500 });

  return { container, item, title, bullets };
}

describe('collectUnbreakableBounds', () => {
  it('splits swiss-single entries between bullets: header+first bullet, then per bullet', () => {
    const { container, item, title, bullets } = buildSwissDom();

    const bounds = collectUnbreakableBounds(container).map((b) => ({
      top: b.top,
      bottom: b.bottom,
      el: b.element,
    }));

    // Sorted by top: title zone (title→first bullet), entry header zone,
    // second bullet, third bullet.
    expect(bounds).toHaveLength(4);
    expect(bounds[0]).toMatchObject({ top: 100, bottom: 250, el: title });
    expect(bounds[1]).toMatchObject({ top: 140, bottom: 250, el: item });
    expect(bounds[2]).toMatchObject({ top: 250, bottom: 340, el: bullets[1] });
    expect(bounds[3]).toMatchObject({ top: 340, bottom: 500, el: bullets[2] });

    // No bound covers the whole entry — otherwise tall projects get pushed
    // wholesale to the next page and leave the previous page half blank.
    expect(bounds.some((b) => b.top === 140 && b.bottom === 500)).toBe(false);
  });

  it('keeps header-only entries (e.g. education rows) whole on swiss-single', () => {
    document.body.innerHTML = `
      <div class="resume-body resume-template-swiss-single">
        <div class="resume-section">
          <h3 class="resume-section-title">教育背景</h3>
          <div class="resume-items">
            <div class="resume-item"><div class="entry-header">某大学</div></div>
          </div>
        </div>
      </div>`;
    const container = document.querySelector('.resume-body') as HTMLElement;
    const item = document.querySelector('.resume-item') as HTMLElement;
    stubRects(container, { top: 0, bottom: 400 });
    stubRects(item, { top: 200, bottom: 260 });
    stubRects(document.querySelector('.resume-section-title') as HTMLElement, {
      top: 170,
      bottom: 195,
    });

    const itemBounds = collectUnbreakableBounds(container).filter((b) => b.element === item);
    expect(itemBounds).toHaveLength(1);
    expect(itemBounds[0]).toMatchObject({ top: 200, bottom: 260 });
  });

  it('treats the whole entry as atomic on non-swiss templates', () => {
    const { container, item } = buildSwissDom();
    container.classList.remove('resume-template-swiss-single');
    container.classList.add('resume-template-modern');

    const itemBounds = collectUnbreakableBounds(container)
      .filter((b) => b.element === item)
      .map((b) => ({ top: b.top, bottom: b.bottom, el: b.element }));
    expect(itemBounds).toEqual([{ top: 140, bottom: 500, el: item }]);
  });

  it('splits swiss-single entries between <ol> rows (DescriptionList renders ol)', () => {
    document.body.innerHTML = `
      <div class="resume-body resume-template-swiss-single">
        <div class="resume-section">
          <h3 class="resume-section-title">工作经历</h3>
          <div class="resume-items">
            <div class="resume-item">
              <div class="entry-header">公司</div>
              <ol>
                <li>row 1</li>
                <li>row 2</li>
              </ol>
            </div>
          </div>
        </div>
      </div>`;
    const container = document.querySelector('.resume-body') as HTMLElement;
    const rows = Array.from(container.querySelectorAll('li')) as HTMLElement[];
    stubRects(container, { top: 0, bottom: 900 });
    stubRects(document.querySelector('.resume-section-title') as HTMLElement, {
      top: 100,
      bottom: 130,
    });
    stubRects(document.querySelector('.resume-item') as HTMLElement, {
      top: 140,
      bottom: 400,
    });
    stubRects(document.querySelector('.entry-header') as HTMLElement, {
      top: 140,
      bottom: 170,
    });
    stubRects(rows[0], { top: 170, bottom: 280 });
    stubRects(rows[1], { top: 280, bottom: 400 });

    const bounds = collectUnbreakableBounds(container).filter((b) => b.element === rows[1]);
    // The second <ol> row gets its own bound, so a tall entry splits between
    // numbered rows instead of moving to the next page as one block.
    expect(bounds).toHaveLength(1);
    expect(bounds[0]).toMatchObject({ top: 280, bottom: 400 });
  });

  it('binds a sub-module label to the first row of its own restart-numbered list', () => {
    document.body.innerHTML = `
      <div class="resume-body resume-template-swiss-single">
        <div class="resume-section">
          <h3 class="resume-section-title">项目经验</h3>
          <div class="resume-items">
            <div class="resume-item">
              <div class="entry-header">项目名</div>
              <ol>
                <li>row 1</li>
                <li>row 2</li>
              </ol>
              <div data-sub-label="">负责内容</div>
              <ol>
                <li>row 3</li>
                <li>row 4</li>
              </ol>
            </div>
          </div>
        </div>
      </div>`;
    const container = document.querySelector('.resume-body') as HTMLElement;
    const item = document.querySelector('.resume-item') as HTMLElement;
    const label = document.querySelector('[data-sub-label]') as HTMLElement;
    const rows = Array.from(container.querySelectorAll('li')) as HTMLElement[];
    stubRects(container, { top: 0, bottom: 900 });
    stubRects(document.querySelector('.resume-section-title') as HTMLElement, {
      top: 100,
      bottom: 130,
    });
    stubRects(item, { top: 140, bottom: 420 });
    stubRects(document.querySelector('.entry-header') as HTMLElement, {
      top: 140,
      bottom: 165,
    });
    stubRects(rows[0], { top: 165, bottom: 200 });
    stubRects(rows[1], { top: 200, bottom: 240 });
    stubRects(label, { top: 240, bottom: 260 });
    stubRects(rows[2], { top: 260, bottom: 300 });
    stubRects(rows[3], { top: 300, bottom: 420 });

    const bounds = collectUnbreakableBounds(container);
    const firstOfSecondGroup = bounds.filter((b) => b.element === rows[2]);

    // The bound starts at the LABEL top, not the li top, so a page break can
    // never leave 负责内容 orphaned at a page bottom.
    expect(firstOfSecondGroup).toHaveLength(1);
    expect(firstOfSecondGroup[0]).toMatchObject({ top: 240, bottom: 300 });
  });

  it('binds a descriptive label to the first row of its body block', () => {
    document.body.innerHTML = `
      <div class="resume-body resume-template-swiss-single">
        <div class="resume-section">
          <h3 class="resume-section-title">项目经验</h3>
          <div class="resume-items">
            <div class="resume-item">
              <div class="entry-header">项目名</div>
              <ol>
                <li>row 1</li>
                <li>row 2</li>
              </ol>
              <div data-sub-label="" data-descriptive="">项目背景：</div>
              <div data-sub-body="">
                <div data-body-row="">背景内容一</div>
                <div data-body-row="">背景内容二</div>
              </div>
            </div>
          </div>
        </div>
      </div>`;
    const container = document.querySelector('.resume-body') as HTMLElement;
    const label = document.querySelector('[data-descriptive]') as HTMLElement;
    const bodyRows = Array.from(document.querySelectorAll('[data-body-row]')) as HTMLElement[];
    const listRows = Array.from(container.querySelectorAll('ol > li')) as HTMLElement[];
    stubRects(container, { top: 0, bottom: 900 });
    stubRects(document.querySelector('.resume-section-title') as HTMLElement, {
      top: 100,
      bottom: 130,
    });
    stubRects(document.querySelector('.resume-item') as HTMLElement, { top: 140, bottom: 430 });
    stubRects(document.querySelector('.entry-header') as HTMLElement, { top: 140, bottom: 165 });
    stubRects(listRows[0], { top: 165, bottom: 200 });
    stubRects(listRows[1], { top: 200, bottom: 240 });
    stubRects(label, { top: 240, bottom: 260 });
    stubRects(bodyRows[0], { top: 260, bottom: 320 });
    stubRects(bodyRows[1], { top: 320, bottom: 430 });

    const bounds = collectUnbreakableBounds(container);
    const firstBodyRow = bounds.filter((b) => b.element === bodyRows[0]);

    // The bound starts at the 项目背景 label top, so a page break can never
    // leave the bold label orphaned from its body content.
    expect(firstBodyRow).toHaveLength(1);
    expect(firstBodyRow[0]).toMatchObject({ top: 240, bottom: 320 });
  });

  it('collects direct section <ol> rows (custom text/skills) as atomic bounds', () => {
    document.body.innerHTML = `
      <div class="resume-body resume-template-swiss-single">
        <div class="resume-section">
          <h3 class="resume-section-title">自我评价</h3>
          <ol>
            <li>point 1</li>
            <li>point 2</li>
          </ol>
        </div>
      </div>`;
    const container = document.querySelector('.resume-body') as HTMLElement;
    const rows = Array.from(container.querySelectorAll('li')) as HTMLElement[];
    stubRects(container, { top: 0, bottom: 600 });
    stubRects(document.querySelector('.resume-section-title') as HTMLElement, {
      top: 100,
      bottom: 130,
    });
    stubRects(rows[0], { top: 130, bottom: 200 });
    stubRects(rows[1], { top: 200, bottom: 270 });

    const rowBounds = collectUnbreakableBounds(container).filter((b) => b.element === rows[1]);
    expect(rowBounds).toHaveLength(1);
    expect(rowBounds[0]).toMatchObject({ top: 200, bottom: 270 });
  });

  it('always honors explicit [data-no-break] even on swiss-single', () => {
    const { container } = buildSwissDom();
    const item = container.querySelector('.resume-item') as HTMLElement;
    item.setAttribute('data-no-break', '');

    const itemBounds = collectUnbreakableBounds(container)
      .filter((b) => b.element === item)
      .map((b) => ({ top: b.top, bottom: b.bottom, el: b.element }));
    expect(itemBounds).toEqual([{ top: 140, bottom: 500, el: item }]);
  });
});
