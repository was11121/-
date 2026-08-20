const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, PageNumber, NumberFormat, AlignmentType, HeadingLevel,
  WidthType, BorderStyle, ShadingType, PageBreak, TableOfContents,
  VerticalAlign, LevelFormat, TableLayoutType, SectionType,
} = require("docx");
const fs = require("fs");
const path = require("path");

const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: NB, bottom: NB, left: NB, right: NB };
const allNoBorders = {
  top: NB, bottom: NB, left: NB, right: NB,
  insideHorizontal: NB, insideVertical: NB,
};

const palettes = {
  "DM-1": {
    bg: "162235", primary: "FFFFFF", accent: "37DCF2",
    cover: { titleColor: "FFFFFF", subtitleColor: "B0B8C0", metaColor: "90989F", footerColor: "687078" },
    table: { headerBg: "1B6B7A", headerText: "FFFFFF", accentLine: "1B6B7A", innerLine: "C8DDE2", surface: "EDF3F5" },
  },
};

function c(hex) {
  return String(hex || "000000").replace("#", "");
}

function splitTitleLines(title, charsPerLine) {
  if (title.length <= charsPerLine) return [title];
  const breakAfter = new Set([..."，。、；：！？的与和及之在于为-_—–·/ \t"]);
  const lines = [];
  let remaining = title;
  while (remaining.length > charsPerLine) {
    let breakAt = -1;
    for (let i = charsPerLine; i >= Math.floor(charsPerLine * 0.6); i--) {
      if (i < remaining.length && breakAfter.has(remaining[i - 1])) {
        breakAt = i;
        break;
      }
    }
    if (breakAt === -1) breakAt = charsPerLine;
    lines.push(remaining.slice(0, breakAt).trim());
    remaining = remaining.slice(breakAt).trim();
  }
  if (remaining) lines.push(remaining);
  if (lines.length > 1 && lines[lines.length - 1].length <= 2) {
    const last = lines.pop();
    lines[lines.length - 1] += last;
  }
  return lines;
}

function calcTitleLayout(title, maxWidthTwips, preferredPt = 40, minPt = 24) {
  const charWidth = (pt) => pt * 20;
  const charsPerLine = (pt) => Math.floor(maxWidthTwips / charWidth(pt));
  let titlePt = preferredPt;
  let lines;
  while (titlePt >= minPt) {
    const cpl = charsPerLine(titlePt);
    if (cpl < 2) { titlePt -= 2; continue; }
    lines = splitTitleLines(title, cpl);
    if (lines.length <= 3) break;
    titlePt -= 2;
  }
  if (!lines || lines.length > 3) {
    const cpl = Math.max(2, charsPerLine(minPt));
    lines = splitTitleLines(title, cpl).slice(0, 3);
    titlePt = minPt;
  }
  return { titlePt, titleLines: lines };
}

function calcCoverSpacing(params) {
  const {
    titleLineCount = 1, titlePt = 36, hasSubtitle = false,
    hasEnglishLabel = false, metaLineCount = 0,
    fixedHeight = 400, pageHeight = 16838,
    marginTop = 0, marginBottom = 0,
  } = params;
  const SAFETY = 1200;
  const usableHeight = pageHeight - marginTop - marginBottom - SAFETY;
  const titleHeight = titleLineCount * (titlePt * 23 + 200);
  const subtitleHeight = hasSubtitle ? (12 * 23 + 600) : 0;
  const englishLabelHeight = hasEnglishLabel ? (9 * 23 + 600) : 0;
  const metaHeight = metaLineCount * (10 * 23 + 100);
  const implicitParaHeight = 3 * 300;
  const contentHeight = titleHeight + subtitleHeight + englishLabelHeight + metaHeight + fixedHeight + implicitParaHeight;
  const remainingSpace = usableHeight - contentHeight;
  const safeRemaining = Math.max(remainingSpace, 400);
  const FOOTER_MIN = 800;
  const rawTop = Math.floor(safeRemaining * 0.45);
  const rawBottom = Math.floor(safeRemaining * 0.45);
  const bottomSpacing = Math.max(rawBottom, FOOTER_MIN);
  const topSpacing = Math.max(rawTop - Math.max(0, FOOTER_MIN - rawBottom), 400);
  const midSpacing = Math.max(safeRemaining - topSpacing - bottomSpacing, 0);
  return { topSpacing, midSpacing, bottomSpacing };
}

function buildCoverR1(config) {
  const P = config.palette;
  const padL = 1200, padR = 800;
  const availableWidth = 11906 - padL - padR - 300;
  const { titlePt, titleLines } = calcTitleLayout(config.title, availableWidth, 40, 24);
  const titleSize = titlePt * 2;
  const spacing = calcCoverSpacing({
    titleLineCount: titleLines.length, titlePt,
    hasSubtitle: !!config.subtitle, hasEnglishLabel: !!config.englishLabel,
    metaLineCount: (config.metaLines || []).length,
    fixedHeight: 400,
  });
  const accentLeft = { style: BorderStyle.SINGLE, size: 8, color: P.accent, space: 12 };
  const children = [];
  children.push(new Paragraph({ spacing: { before: spacing.topSpacing } }));
  if (config.englishLabel) {
    children.push(new Paragraph({
      indent: { left: padL, right: padR }, spacing: { after: 500 },
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: P.accent, space: 8 } },
      children: [new TextRun({
        text: config.englishLabel.split("").join("  "),
        size: 18, color: P.accent, font: { ascii: "Calibri", eastAsia: "SimHei" }, characterSpacing: 40,
      })],
    }));
  }
  for (let i = 0; i < titleLines.length; i++) {
    children.push(new Paragraph({
      indent: { left: padL },
      spacing: { after: i < titleLines.length - 1 ? 100 : 300, line: Math.ceil(titlePt * 23), lineRule: "atLeast" },
      children: [new TextRun({
        text: titleLines[i], size: titleSize, bold: true,
        color: P.titleColor, font: { eastAsia: "SimHei", ascii: "Arial" },
      })],
    }));
  }
  if (config.subtitle) {
    children.push(new Paragraph({
      indent: { left: padL }, spacing: { after: 800 },
      children: [new TextRun({
        text: config.subtitle, size: 24, color: P.subtitleColor,
        font: { eastAsia: "Microsoft YaHei", ascii: "Arial" },
      })],
    }));
  }
  for (const line of (config.metaLines || [])) {
    children.push(new Paragraph({
      indent: { left: padL + 200 }, spacing: { after: 80 },
      border: { left: accentLeft },
      children: [new TextRun({
        text: line, size: 24, color: P.metaColor,
        font: { eastAsia: "Microsoft YaHei", ascii: "Arial" },
      })],
    }));
  }
  children.push(new Paragraph({ spacing: { before: spacing.bottomSpacing } }));
  children.push(new Paragraph({
    indent: { left: padL, right: padR },
    border: { top: { style: BorderStyle.SINGLE, size: 2, color: P.accent, space: 8 } },
    spacing: { before: 200 },
    children: [
      new TextRun({ text: config.footerLeft || "", size: 16, color: P.footerColor, font: { ascii: "Arial" } }),
      new TextRun({ text: "                                        " }),
      new TextRun({ text: config.footerRight || "", size: 16, color: P.footerColor, font: { ascii: "Arial" } }),
    ],
  }));
  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      height: { value: 16838, rule: "exact" },
      children: [new TableCell({
        shading: { type: ShadingType.CLEAR, fill: P.bg },
        borders: noBorders,
        verticalAlign: VerticalAlign.TOP,
        children,
      })],
    })],
  })];
}

const bodyColor = "000000";
const headingColor = "0A1628";
const T = palettes["DM-1"].table;

function run(text, opts = {}) {
  return new TextRun({
    text,
    size: opts.size || 24,
    bold: !!opts.bold,
    italics: !!opts.italics,
    color: opts.color || bodyColor,
    font: { ascii: "Times New Roman", eastAsia: opts.eastAsia || "SimSun" },
  });
}

function p(text, extra = {}) {
  return new Paragraph({
    alignment: extra.align || AlignmentType.JUSTIFIED,
    spacing: { after: extra.after ?? 160, before: extra.before ?? 0, line: 312 },
    indent: extra.noIndent ? undefined : { firstLine: extra.firstLine ?? 480 },
    children: [run(text, extra)],
  });
}

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200, line: 312 },
    children: [new TextRun({
      text, bold: true, size: 32, color: headingColor,
      font: { ascii: "Times New Roman", eastAsia: "SimHei" },
    })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 140, line: 312 },
    children: [new TextRun({
      text, bold: true, size: 30, color: headingColor,
      font: { ascii: "Times New Roman", eastAsia: "SimHei" },
    })],
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 220, after: 120, line: 312 },
    children: [new TextRun({
      text, bold: true, size: 28, color: headingColor,
      font: { ascii: "Times New Roman", eastAsia: "SimHei" },
    })],
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 80, line: 312 },
    children: [run(text)],
  });
}

function codeBlock(text) {
  return new Paragraph({
    shading: { type: ShadingType.CLEAR, fill: "F4F8FC" },
    spacing: { after: 120, before: 80, line: 276 },
    indent: { left: 200, right: 200 },
    children: [new TextRun({
      text, size: 18, color: "1A2B40",
      font: { ascii: "Courier New", eastAsia: "SimSun" },
    })],
  });
}

function caption(text) {
  return new Paragraph({
    keepNext: true,
    spacing: { before: 200, after: 80, line: 276 },
    children: [run(text, { size: 21, bold: true, eastAsia: "SimHei" })],
  });
}

function cell(text, opts = {}) {
  const isHeader = !!opts.header;
  return new TableCell({
    width: { size: opts.width || 20, type: WidthType.PERCENTAGE },
    shading: { type: ShadingType.CLEAR, fill: isHeader ? T.headerBg : (opts.alt ? T.surface : "FFFFFF") },
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    children: [new Paragraph({
      spacing: { after: 0, line: 276 },
      children: [new TextRun({
        text: String(text ?? ""),
        bold: isHeader,
        size: 18,
        color: isHeader ? T.headerText : bodyColor,
        font: { ascii: "Times New Roman", eastAsia: isHeader ? "SimHei" : "SimSun" },
      })],
    })],
  });
}

function table(headers, rows, widths) {
  const w = widths || headers.map(() => Math.floor(100 / headers.length));
  const headerRow = new TableRow({
    tableHeader: true,
    cantSplit: true,
    children: headers.map((h, i) => cell(h, { header: true, width: w[i] })),
  });
  const dataRows = rows.map((r, idx) => new TableRow({
    cantSplit: true,
    children: r.map((v, i) => cell(v, { alt: idx % 2 === 0, width: w[i] })),
  }));
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: T.accentLine },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: T.accentLine },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 1, color: T.innerLine },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: [headerRow, ...dataRows],
  });
}

function tocBlock() {
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 480, after: 360 },
      children: [new TextRun({
        text: "目  录", bold: true, size: 32,
        font: { eastAsia: "SimHei", ascii: "Times New Roman" },
      })],
    }),
    new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" }),
    new Paragraph({
      spacing: { before: 200 },
      children: [new TextRun({
        text: "\u6ce8\uff1a\u672c\u76ee\u5f55\u7531\u5b57\u6bb5\u4ee3\u7801\u751f\u6210\u3002\u8bf7\u5728 Word \u4e2d\u53f3\u952e\u76ee\u5f55\u5e76\u9009\u62e9\u201c\u66f4\u65b0\u57df\u201d\uff0c\u4ee5\u786e\u4fdd\u9875\u7801\u51c6\u786e\u3002",
        italics: true, size: 18, color: "888888",
        font: { eastAsia: "SimSun", ascii: "Times New Roman" },
      })],
    }),
  ];
}

function styles() {
  return {
    default: {
      document: {
        run: { font: { ascii: "Times New Roman", eastAsia: "SimSun" }, size: 24, color: "000000" },
        paragraph: { spacing: { line: 312 } },
      },
    },
  };
}

function numbering() {
  return {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }],
      },
    ],
  };
}

function header(title) {
  return new Header({
    children: [new Paragraph({
      border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: T.accentLine, space: 4 } },
      spacing: { after: 80 },
      children: [
        new TextRun({ text: "MyAgent Unified", size: 18, color: "1B6B7A", font: { ascii: "Calibri", eastAsia: "SimHei" } }),
        new TextRun({ text: "  |  " + title, size: 16, color: "6878A0", font: { ascii: "Calibri", eastAsia: "SimSun" } }),
      ],
    })],
  });
}

function footer() {
  return new Footer({
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      border: { top: { style: BorderStyle.SINGLE, size: 6, color: T.accentLine, space: 6 } },
      children: [
        new TextRun({ text: "\u7b2c ", size: 18, font: { eastAsia: "SimSun" } }),
        new TextRun({ children: [PageNumber.CURRENT], size: 18 }),
        new TextRun({ text: " \u9875", size: 18, font: { eastAsia: "SimSun" } }),
      ],
    })],
  });
}

function coverSection(title, subtitle, englishLabel, metaLines) {
  const pal = palettes["DM-1"];
  return {
    properties: {
      page: { size: { width: 11906, height: 16838 }, margin: { top: 0, bottom: 0, left: 0, right: 0 } },
    },
    children: buildCoverR1({
      title, subtitle, englishLabel, metaLines,
      footerLeft: "MyAgent Unified",
      footerRight: "CONFIDENTIAL / INTERNAL",
      palette: {
        bg: pal.bg,
        titleColor: pal.cover.titleColor,
        subtitleColor: pal.cover.subtitleColor,
        metaColor: pal.cover.metaColor,
        accent: pal.accent,
        footerColor: pal.cover.footerColor,
      },
    }),
  };
}

function tocSection() {
  return {
    properties: {
      type: SectionType.NEXT_PAGE,
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, bottom: 1440, left: 1701, right: 1417 },
        pageNumbers: { start: 1, formatType: NumberFormat.LOWER_ROMAN },
      },
    },
    headers: { default: header("\u6587\u6863\u76ee\u5f55") },
    footers: { default: footer() },
    children: tocBlock(),
  };
}

function bodySection(children, headerTitle) {
  return {
    properties: {
      type: SectionType.NEXT_PAGE,
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, bottom: 1440, left: 1701, right: 1417 },
        pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL },
      },
    },
    headers: { default: header(headerTitle) },
    footers: { default: footer() },
    children,
  };
}

function overviewBody() {
  return [
    h1("1. 用一句话说清这个项目"),
    p("MyAgent Unified \u662f\u4e00\u4e2a\u672c\u5730\u8fd0\u884c\u7684\u201c\u73b0\u5b9e\u8865\u4e01\u667a\u80fd\u4f53\u201d\u3002\u5b83\u4e0d\u662f\u7eaf\u804a\u5929\u673a\u5668\u4eba\uff0c\u800c\u662f\u628a\u56db\u4ef6\u4e8b\u88c5\u8fdb\u540c\u4e00\u4e2a Agent\uff1a\u8bb0\u4f4f\u4f60\u662f\u8c01\u3001\u4ece\u672c\u5730\u6587\u6863\u91cc\u627e\u4f9d\u636e\u3001\u628a\u4efb\u52a1\u53d8\u6210\u53ef\u786e\u8ba4\u53ef\u56de\u6eda\u7684\u8865\u4e01\u3001\u5e76\u5728\u4f60\u6253\u8f6c\u5708\u65f6\u7ed9\u4e00\u70b9\u63d0\u793a\u3002"),
    p("\u4f60\u53ef\u4ee5\u628a\u5b83\u60f3\u8c61\u6210\uff1a\u4e00\u4f4d\u5e26\u7740\u201c\u4e2a\u4eba\u7b14\u8bb0\u672c + \u516c\u53f8\u6863\u6848\u67dc + \u9879\u76ee\u79d8\u4e66 + \u5b89\u5168\u5ba1\u6279\u201d\u7684\u52a9\u624b\u3002\u5b83\u9ed8\u8ba4\u8dd1\u5728\u4f60\u7684\u7535\u8111\u4e0a\uff08http://127.0.0.1:8091\uff09\uff0c\u8bb0\u5fc6\u548c\u6587\u6863\u90fd\u843d\u5728\u672c\u5730 SQLite / JSON \u91cc\uff0c\u4e0d\u4f9d\u8d56\u4e91\u7aef\u8d26\u53f7\u4f53\u7cfb\u3002"),
    p("\u5b83\u80fd\u505a\u5230\u4ec0\u4e48\u7a0b\u5ea6\uff1f\u5bf9\u4e8e\u5355\u4eba\u6216\u5c0f\u56e2\u961f\uff0c\u5b83\u5df2\u7ecf\u80fd\u5b8c\u6210\uff1a\u767b\u5f55\u9694\u79bb\u3001\u4e2a\u4eba\u753b\u50cf\u8bb0\u5fc6\u3001\u591a\u683c\u5f0f\u6587\u6863\u68c0\u7d22\u3001\u4efb\u52a1\u770b\u677f\u3001\u8865\u4e01\u786e\u8ba4/\u56de\u6eda\u3001QQ Webhook \u63a5\u5165\u3002\u5b83\u8fd8\u4e0d\u662f\u4f01\u4e1a\u7ea7 SaaS\uff1a\u6ca1\u6709\u591a\u79df\u6237\u4e91\u90e8\u7f72\u3001\u6ca1\u6709\u5411\u91cf\u6570\u636e\u5e93\u7ea7\u8bed\u4e49\u68c0\u7d22\u3001\u6ca1\u6709\u5b8c\u6574 RBAC \u6743\u9650\u77e9\u9635\u3001\u4e5f\u6ca1\u6709\u81ea\u52a8\u6267\u884c\u5916\u90e8\u7cfb\u7edf\u53d8\u66f4\u3002\u5b83\u7684\u8bbe\u8ba1\u4fe1\u6761\u662f\uff1a\u5148\u8ba9\u53d8\u66f4\u53ef\u89c1\u3001\u53ef\u786e\u8ba4\u3001\u53ef\u64a4\u9500\uff0c\u518d\u8c08\u81ea\u52a8\u5316\u3002"),

    h1("2. 给完全没接触过代码的人：它怎么工作"),
    h2("2.1 一次对话发生了什么"),
    p("\u4f60\u5728\u7f51\u9875\u91cc\u8f93\u5165\u4e00\u53e5\u8bdd\u3002\u524d\u7aef\u628a\u8fd9\u53e5\u8bdd\u88c5\u6210\u4e00\u4e2a\u201c\u4fe1\u5c01\u201d\uff08InteractionEnvelope\uff09\uff0c\u91cc\u9762\u5199\u660e\u8c01\u53d1\u7684\u3001\u4ece\u54ea\u4e2a\u6e20\u9053\u6765\u3001\u8bf4\u4e86\u4ec0\u4e48\u3001\u5c5e\u4e8e\u54ea\u4e2a\u5de5\u4f5c\u533a\u3002\u540e\u7aef Flask \u63a5\u5230\u8fd9\u4e2a\u4fe1\u5c01\u540e\uff0c\u4e0d\u4f1a\u76f4\u63a5\u76f8\u4fe1\u4f60\u81ea\u62a5\u7684 user_id\uff1a\u5982\u679c\u4f60\u5df2\u767b\u5f55\uff0c\u4f1a\u5f3a\u5236\u6539\u6210\u4ee4\u724c\u91cc\u7684\u771f\u5b9e\u7528\u6237\u540d\uff0c\u9632\u6b62\u5192\u5145\u522b\u4eba\u5199\u8bb0\u5fc6\u3002"),
    p("\u63a5\u4e0b\u6765 UnifiedAgent \u4f1a\u540c\u65f6\u505a\u51e0\u4ef6\u4e8b\uff1a\u4ece\u4f60\u81ea\u5df1\u7684 SQLite \u91cc\u53d6\u51fa\u957f\u671f\u8bb0\u5fc6\uff1b\u5982\u679c\u4f60\u7684\u8bdd\u50cf\u5728\u67e5\u8d44\u6599\uff0c\u5c31\u53bb\u77e5\u8bc6\u5e93\u91cc\u641c\uff1b\u5982\u679c\u4f60\u5728\u5efa\u4efb\u52a1\u6216\u540c\u6b65\u8fdb\u5c55\uff0c\u53ea\u751f\u6210\u201c\u8349\u7a3f\u8865\u4e01\u201d\u800c\u4e0d\u76f4\u63a5\u6539\u6570\u636e\u5e93\uff1b\u7136\u540e\u628a\u8bb0\u5fc6\u4e0e\u5f15\u7528\u4e00\u8d77\u4ea4\u7ed9\u5927\u6a21\u578b\uff08\u9ed8\u8ba4 DeepSeek\uff09\u751f\u6210\u56de\u7b54\u3002\u6700\u540e\u628a\u8fd9\u6b21\u5bf9\u8bdd\u8bb0\u5165\u4f60\u7684\u533a\u95f4\uff0c\u5e76\u7528\u89c4\u5219\u63d0\u53d6\u504f\u597d\u3001\u8eab\u4efd\u3001\u8fb9\u754c\u7b49\u957f\u671f\u8bb0\u5fc6\u3002"),
    h2("2.2 为什么叫“现实补丁”"),
    p("\u8f6f\u4ef6\u754c\u6709\u4e2a\u4e60\u60ef\uff1a\u6539\u4ee3\u7801\u5148\u63d0 Pull Request\uff0c\u5ba1\u8fc7\u518d\u5408\u5e76\u3002\u8fd9\u4e2a\u9879\u76ee\u628a\u540c\u6837\u601d\u8def\u7528\u5728\u201c\u73b0\u5b9e\u4e16\u754c\u7684\u72b6\u6001\u201d\u4e0a\u3002\u4f60\u8bf4\u201c\u521b\u5efa\u4e00\u4e2a\u4efb\u52a1\uff1a\u5b8c\u6210\u8054\u8c03\u201d\u65f6\uff0c\u7cfb\u7edf\u4e0d\u4f1a\u9a6c\u4e0a\u628a\u770b\u677f\u91cc\u63d2\u4e00\u6761\u4efb\u52a1\uff0c\u800c\u662f\u5148\u751f\u6210\u4e00\u4e2a status=draft \u7684 RealityPatch\u3002\u4f60\u70b9\u786e\u8ba4\uff0c\u4efb\u52a1\u624d\u771f\u6b63\u5199\u5165\uff1b\u4f60\u70b9\u56de\u6eda\uff0c\u4efb\u52a1\u4f1a\u6309 rollback_data \u6062\u590d\u3002\u8fd9\u5c31\u662f\u201c\u8865\u4e01\u201d\uff1a\u5bf9\u73b0\u5b9e\u72b6\u6001\u7684\u4e00\u6b21\u53ef\u5ba1\u8ba1\u53d8\u66f4\u3002"),

    h1("3. 整体架构与目录结构"),
    h2("3.1 运行时鸟瞰"),
    p("\u6240\u6709\u6e20\u9053\uff08Web \u63a7\u5236\u53f0\u3001QQ OneBot\uff09\u90fd\u53ea\u505a\u4e00\u4ef6\u4e8b\uff1a\u628a\u5916\u90e8\u4e8b\u4ef6\u7ffb\u8bd1\u6210 InteractionEnvelope\uff0c\u518d\u628a ResponseEnvelope \u9001\u56de\u53bb\u3002\u4e1a\u52a1\u903b\u8f91\u5168\u90e8\u5728 UnifiedAgent \u91cc\u3002\u8fd9\u53eb\u201c\u4e00\u4e2a\u6838\u5fc3\uff0c\u591a\u4e2a\u63a5\u53e3\u201d\u3002"),
    caption("\u8868 1  \u9879\u76ee\u76ee\u5f55\u4e0e\u804c\u8d23"),
    table(
      ["\u76ee\u5f55/\u6587\u4ef6", "\u8d23\u4efb", "\u6280\u672f\u6808", "\u76ee\u6807"],
      [
        ["app.py", "HTTP \u5165\u53e3\u3001\u9274\u6743\u3001\u8def\u7531", "Flask 3 + python-dotenv", "\u628a Web/QQ \u8bf7\u6c42\u7edf\u4e00\u8fdb\u6838\u5fc3"],
        ["static/index.html", "\u524d\u7aef\u63a7\u5236\u53f0", "\u539f\u751f HTML + Tailwind CDN + FontAwesome + marked.js", "\u767b\u5f55\u3001\u5bf9\u8bdd\u3001\u770b\u677f\u3001\u77e5\u8bc6\u5e93\u3001\u753b\u50cf"],
        ["unified_agent/", "Agent \u6838\u5fc3\u4e0e\u534f\u8bae", "Python dataclass + urllib", "\u7f16\u6392\u8bb0\u5fc6/\u77e5\u8bc6\u5e93/\u79d8\u4e66/LLM"],
        ["auth_runtime/", "\u8d26\u53f7\u4e0e\u4ee4\u724c", "sqlite3 + pbkdf2_hmac", "\u767b\u5f55\u4e0e\u89d2\u8272\u9694\u79bb"],
        ["memory_runtime/", "\u7528\u6237\u8bb0\u5fc6\u533a\u95f4", "\u6bcf\u7528\u6237\u72ec\u7acb SQLite", "\u957f\u671f\u753b\u50cf\u4e0d\u4e32\u6d41"],
        ["library_runtime/", "\u672c\u5730\u6587\u6863\u9986", "pypdf / python-docx / pptx / openpyxl + SHA-256", "\u53ef\u8ffd\u6eaf\u7684\u5f15\u7528\u56de\u7b54"],
        ["secretary_runtime/", "\u9879\u76ee\u79d8\u4e66\u4e0e\u8865\u4e01", "sqlite3 \u72b6\u6001\u673a", "\u8349\u7a3f\u2192\u786e\u8ba4\u2192\u56de\u6eda"],
        ["tip_engine/", "\u542f\u53d1\u5f0f\u63d0\u793a", "\u7eaf Python \u89c4\u5219 + \u51b7\u5374", "\u4e0d\u6253\u65ad\u4e3b\u56de\u7b54\u7684\u4fa7\u8fb9\u63d0\u793a"],
        ["cognitive_engine/", "\u53ef\u9009\u8ba4\u77e5\u8ba1\u7b97", "Python fallback + ctypes/C++", "\u53cd\u9988\u6253\u5206\u4e0e\u65b9\u5411\u504f\u79fb"],
        ["adapters/", "\u6e20\u9053\u8bf4\u660e\u4e0e\u517c\u5bb9\u5c42", "OneBot / \u65e7\u9879\u76ee\u6865", "\u4e0d\u5728\u9002\u914d\u5668\u91cc\u5199\u4e1a\u52a1"],
        ["tests/", "\u81ea\u52a8\u6d4b\u8bd5", "unittest", "\u8bb0\u5fc6\u9694\u79bb\u3001\u8865\u4e01\u3001\u9274\u6743"],
        ["data/", "\u672c\u5730\u6301\u4e45\u5316", "SQLite + JSON + txt", "\u8dd1\u5728\u78c1\u76d8\u4e0a\u7684\u771f\u5b9e\u6570\u636e"],
        ["start.bat", "\u4e00\u952e\u542f\u52a8", "Windows CMD", "\u68c0\u6d4b Python \u5e76\u6253\u5f00\u6d4f\u89c8\u5668"],
      ],
      [22, 22, 28, 28]
    ),
    h2("3.2 数据落在哪里"),
    p("\u9ed8\u8ba4\u6570\u636e\u76ee\u5f55\u662f ./data\uff08\u53ef\u7528 MYAGENT_DATA_DIR \u6539\uff09\u3002\u8fd9\u662f\u201c\u7269\u7406\u9694\u79bb\u201d\u7684\u5173\u952e\uff1a\u4e0d\u540c\u7528\u6237\u7684\u8bb0\u5fc6\u4e0d\u662f\u540c\u4e00\u5f20\u8868\u91cc\u52a0 user_id \u5b57\u6bb5\uff0c\u800c\u662f\u76f4\u63a5\u4e0d\u540c\u6587\u4ef6\u3002"),
    table(
      ["\u8def\u5f84", "\u5185\u5bb9", "\u8c01\u80fd\u8bfb"],
      [
        ["data/auth.sqlite3", "\u7528\u6237\u8868 + \u4ee4\u724c\u8868", "\u8ba4\u8bc1\u670d\u52a1"],
        ["data/users/<uid>/memory.sqlite3", "\u8bb0\u5fc6\u3001\u4ea4\u4e92\u3001\u53cd\u9988", "\u672c\u4eba\uff1b\u7ba1\u7406\u5458\u53ef\u7a7f\u900f"],
        ["data/library/index.json", "\u6587\u6863\u7d22\u5f15", "\u5168\u4f53\u767b\u5f55\u7528\u6237\u53ef\u68c0\u7d22"],
        ["data/library/documents/*.txt", "\u6e05\u6d17\u540e\u6b63\u6587", "\u77e5\u8bc6\u5e93\u68c0\u7d22"],
        ["data/secretary.sqlite3", "\u9879\u76ee\u3001\u4efb\u52a1\u3001\u8865\u4e01\u3001\u5ba1\u8ba1", "\u5de5\u4f5c\u533a\u5171\u4eab\uff08\u975e\u4e2a\u4eba\u9694\u79bb\uff09"],
      ],
      [36, 32, 32]
    ),

    h1("4. 技术栈总览（小白也能看懂的版本）"),
    p("\u6280\u672f\u6808\u5c31\u662f\u201c\u7528\u4e86\u54ea\u4e9b\u73b0\u6210\u5de5\u5177\u201d\u3002\u8fd9\u4e2a\u9879\u76ee\u523b\u610f\u4fdd\u6301\u8f7b\u91cf\uff1a\u540e\u7aef\u51e0\u4e4e\u53ea\u7528 Python \u6807\u51c6\u5e93 + Flask + \u51e0\u4e2a\u6587\u6863\u89e3\u6790\u5e93\uff1b\u524d\u7aef\u4e0d\u6253\u5305\u3001\u4e0d\u7528 React\uff0c\u5355\u6587\u4ef6 HTML \u5c31\u80fd\u8dd1\u3002"),
    caption("\u8868 2  \u6280\u672f\u9009\u578b\u4e0e\u539f\u56e0"),
    table(
      ["\u5c42\u6b21", "\u9009\u578b", "\u4e3a\u4ec0\u4e48\u8fd9\u4e48\u9009", "\u80fd\u5230\u4ec0\u4e48\u7a0b\u5ea6"],
      [
        ["Web \u670d\u52a1", "Flask 3", "\u8f7b\u91cf\u3001\u8def\u7531\u6e05\u695a\u3001\u6d4b\u8bd5\u5ba2\u6237\u7aef\u597d\u7528", "\u672c\u673a\u5355\u8fdb\u7a0b\u5f00\u53d1\u670d\u52a1\uff0c\u975e\u9ad8\u5e76\u53d1\u751f\u4ea7"],
        ["\u524d\u7aef", "\u5355\u9875 HTML + Tailwind CDN", "\u96f6\u6784\u5efa\u3001\u53cc\u51fb start.bat \u5373\u53ef", "\u5b8c\u6574\u63a7\u5236\u53f0\uff0c\u975e SPA \u5de5\u7a0b"],
        ["\u8d26\u53f7", "sqlite3 + PBKDF2-SHA256", "\u96f6\u7b2c\u4e09\u65b9\u91cd\u578b\u4f9d\u8d56", "\u5355\u673a\u591a\u7528\u6237\u8db3\u591f\uff0c\u975e OAuth"],
        ["\u8bb0\u5fc6", "\u6bcf\u7528\u6237\u4e00\u4e2a SQLite", "\u7269\u7406\u9694\u79bb\u6bd4 SQL WHERE \u66f4\u96be\u6cc4", "\u4e2a\u4eba\u753b\u50cf\u7ea7\uff0c\u975e\u77e2\u91cf\u8bb0\u5fc6"],
        ["\u77e5\u8bc6\u5e93", "\u6587\u4ef6\u89e3\u6790 + JSON \u7d22\u5f15 + \u4e2d\u6587\u53cc\u5b57\u68c0\u7d22", "\u79bb\u7ebf\u53ef\u7528\u3001\u53ef\u5f15\u7528", "\u5173\u952e\u8bcd\u53ec\u56de\uff0c\u975e\u5411\u91cf RAG"],
        ["\u5927\u6a21\u578b", "OpenAI \u517c\u5bb9 Chat Completions", "DeepSeek \u5b98\u65b9 API", "\u65ad\u7f51\u65f6\u81ea\u52a8\u964d\u7ea7\u5230\u89c4\u5219\u56de\u7b54"],
        ["\u79d8\u4e66", "SQLite \u72b6\u6001\u673a", "\u8865\u4e01\u53ef\u5ba1\u8ba1", "\u4efb\u52a1 CRUD + \u540c\u6b65\u8349\u7a3f"],
        ["\u8ba4\u77e5\u5f15\u64ce", "Python\uff0c\u53ef\u63d2 C++ DLL", "\u9ad8\u9891\u8ba1\u7b97\u53ef\u52a0\u901f", "\u7f3a\u5e93\u65f6\u5b8c\u6574\u53ef\u7528"],
      ],
      [16, 24, 28, 32]
    ),
    p("\u4f9d\u8d56\u6e05\u5355\u53ea\u6709\uff1aflask\u3001pypdf\u3001python-docx\u3001python-pptx\u3001openpyxl\u3002LLM \u8c03\u7528\u7528\u6807\u51c6\u5e93 urllib\uff0c\u4e0d\u5f15\u5165 openai SDK\u3002\u73af\u5883\u53d8\u91cf\u89c1 .env\uff1aMODEL_API_KEY\u3001BASE_URL\u3001CURRENT_MODEL\u3001MYAGENT_DATA_DIR\u3001COGNITIVE_ENGINE_LIBRARY\u3002"),

    h1("5. 认证模块 auth_runtime：谁可以进来"),
    h2("5.1 目标"),
    p("\u628a\u201c\u8c01\u5728\u7528\u8fd9\u4e2a\u7cfb\u7edf\u201d\u4ece\u81ea\u7531\u586b user_id \u5347\u7ea7\u6210\u771f\u6b63\u8d26\u53f7\u3002\u6ca1\u6709\u8fd9\u4e00\u6b65\uff0c\u4efb\u4f55\u4eba\u90fd\u53ef\u4ee5\u5728\u9876\u90e8\u8f93\u5165 alice \u7136\u540e\u770b\u522b\u4eba\u8bb0\u5fc6\u3002\u6709\u4e86\u8ba4\u8bc1\uff0c\u8bb0\u5fc6\u624d\u7b97\u771f\u6b63\u9694\u79bb\u3002"),
    h2("5.2 技术实现"),
    bullet("\u5b58\u50a8\uff1adata/auth.sqlite3\uff0cusers \u4e0e tokens \u4e24\u5f20\u8868\uff0c\u5916\u952e ON DELETE CASCADE\u3002"),
    bullet("\u5bc6\u7801\uff1ahashlib.pbkdf2_hmac('sha256', password, salt, 100000)\uff0c\u76d0\u662f 32 \u4f4d hex\u3002\u4e0d\u5b58\u660e\u6587\u5bc6\u7801\u3002"),
    bullet("\u4ee4\u724c\uff1atok_ + uuid\uff0c\u9ed8\u8ba4 72 \u5c0f\u65f6\u8fc7\u671f\u3002"),
    bullet("\u89d2\u8272\uff1aadmin / user\u3002\u6ce8\u518c\u63a5\u53e3\u5f3a\u5236 role=user\uff0c\u4e0d\u80fd\u81ea\u6ce8\u518c\u6210\u7ba1\u7406\u5458\u3002"),
    bullet("\u9ed8\u8ba4\u8d26\u53f7\uff1aadmin/admin123\uff1balice/123456\uff1bbob/123456\u3002\u9996\u6b21\u542f\u52a8\u81ea\u52a8\u5199\u5165\u3002"),
    h2("5.3 能做到什么程度"),
    p("\u80fd\u505a\u5230\uff1a\u767b\u5f55\u53d1\u4ee4\u3001/v1/auth/me \u6821\u9a8c\u3001\u6ce8\u9500\u5931\u6548\u3001\u666e\u901a\u7528\u6237 403 \u8de8\u7528\u6237\u8bb0\u5fc6\u3001\u7ba1\u7406\u5458\u53ef\u5217\u8868\u5168\u91cf\u753b\u50cf\u3002\u505a\u4e0d\u5230\uff1a\u9a8c\u8bc1\u7801\u3001\u90ae\u4ef6\u627e\u56de\u5bc6\u7801\u3001SSO\u3001\u7ec6\u7c92\u5ea6\u529f\u80fd\u6743\u9650\u3001\u8d85\u65f6\u81ea\u52a8\u5237\u65b0\u3001\u9632\u66b4\u529b\u7834\u89e3\u9501\u5b9a\u3002\u5b83\u662f\u672c\u5730\u591a\u7528\u6237\u4ea7\u54c1\u7684\u5408\u7406\u8ba4\u8bc1\u5e95\u7ebf\u3002"),

    h1("6. 记忆模块 memory_runtime：它如何记住你"),
    h2("6.1 目标"),
    p("\u8ba9 Agent \u8de8\u4f1a\u8bdd\u8bb0\u4f4f\u4f60\u7684\u504f\u597d\u3001\u8eab\u4efd\u3001\u9700\u6c42\u3001\u8fb9\u754c\u548c\u7ea0\u6b63\u3002\u660e\u5929\u4f60\u518d\u6765\uff0c\u5b83\u4ecd\u7136\u77e5\u9053\u4f60\u559c\u6b22\u62ff\u94c1\u800c\u4e0d\u662f\u7f8e\u5f0f\u3002\u66f4\u91cd\u8981\u7684\u662f\uff1aAlice \u7684\u559c\u597d\u7edd\u4e0d\u80fd\u6cc4\u5230 Bob \u7684\u5bf9\u8bdd\u91cc\u3002"),
    h2("6.2 技术实现"),
    bullet("\u7269\u7406\u9694\u79bb\uff1a\u7528\u6237 ID \u4f1a\u88ab\u6e05\u6d17\u6210\u5b89\u5168\u6587\u4ef6\u540d\uff0c\u7136\u540e\u5efa data/users/<id>/memory.sqlite3\u3002"),
    bullet("\u4e09\u5f20\u8868\uff1amemories\uff08\u957f\u671f\u8bb0\u5fc6\uff09\u3001interactions\uff08\u5bf9\u8bdd\u6d41\u6c34\uff09\u3001feedback\uff08\u786e\u8ba4/\u62d2\u7edd/\u9057\u5fd8\uff09\u3002"),
    bullet("\u63d0\u53d6\u89c4\u5219\u4fdd\u5b88\uff1a\u7528\u6b63\u5219\u5339\u914d\u201c\u6211\u559c\u6b22\u201d\u201c\u4e0d\u8981\u201d\u201c\u8bb0\u4f4f\u201d\u201c\u6211\u53eb\u201d\u7b49\u53e5\u5f0f\uff0c\u4e0d\u7528\u5927\u6a21\u578b\u731c\u4f60\u7684\u9690\u79c1\u3002"),
    bullet("\u7c7b\u522b\uff1apreference_like\u3001preference_dislike\u3001need\u3001identity\u3001boundary\u3001instruction\u3001correction\u3002"),
    bullet("\u7f6e\u4fe1\u5ea6\u4e0e\u53bb\u91cd\uff1a\u540c\u7c7b\u540c\u5185\u5bb9\u4f1a\u7d2f\u52a0 occurrence_count \u5e76\u4fdd\u7559\u66f4\u9ad8\u7f6e\u4fe1\u5ea6\u3002"),
    bullet("\u9057\u5fd8\uff1a\u6309 evidence \u94fe\u4e00\u8d77 forgotten\uff0c\u907f\u514d\u540c\u4e00\u53e5\u8bdd\u63d0\u51fa\u7684\u591a\u6761\u5019\u9009\u53ea\u5220\u4e00\u534a\u3002"),
    h2("6.3 能做到什么程度"),
    p("\u80fd\uff1a\u81ea\u52a8\u6c89\u6dc0\u660e\u786e\u53e3\u5934\u7684\u504f\u597d\u4e0e\u8eab\u4efd\uff1b\u7528\u8bb0\u5fc6\u6ce8\u5165 LLM system prompt\uff1b\u7528\u6237\u70b9\u8d5e/\u8e29/\u5220\uff1b\u7ba1\u7406\u5458\u770b\u5206\u7c7b\u7edf\u8ba1\u3002\u4e0d\u80fd\uff1a\u4ece\u957f\u7bc7\u9690\u542b\u610f\u601d\u91cc\u63d0\u53d6\u590d\u6742\u753b\u50cf\uff08\u6ca1\u6709 embedding \u8bb0\u5fc6\uff09\uff1b\u8de8\u8bbe\u5907\u4e91\u540c\u6b65\uff1b\u81ea\u52a8\u65f6\u95f4\u8870\u51cf\u4efb\u52a1\u8fd8\u672a\u505a\u6210\u5b9a\u65f6\u4f5c\u4e1a\u3002\u5b83\u662f\u201c\u53ef\u89e3\u91ca\u3001\u53ef\u64a4\u9500\u7684\u89c4\u5219\u8bb0\u5fc6\u201d\uff0c\u4e0d\u662f ChatGPT \u90a3\u79cd\u9ed1\u76d2\u957f\u8bb0\u5fc6\u3002"),

    h1("7. 知识库 library_runtime：本地图书馆"),
    h2("7.1 目标"),
    p("\u8ba9\u56de\u7b54\u6709\u4f9d\u636e\u3002\u4f60\u4e0a\u4f20 PDF/\u535a\u5ba2/\u8868\u683c\u540e\uff0cAgent \u4e0d\u80fd\u80e1\u7f16\u4e00\u4e2a\u4e0a\u7ebf\u65e5\u671f\uff0c\u800c\u8981\u80fd\u6307\u51fa\u201c\u6765\u81ea\u54ea\u7bc7\u6587\u6863\u7684\u54ea\u6bb5\u8bdd\u201d\u3002"),
    h2("7.2 技术实现"),
    bullet("DocumentProcessor \u6309\u6269\u5c55\u540d\u5206\u53d1\uff1atxt/md \u76f4\u63a5\u89e3\u7801\uff1bjson \u683c\u5f0f\u5316\uff1bcsv \u62fc\u6210\u8868\uff1bpdf \u7528 pypdf \u6309\u9875\uff1bdocx \u7528 python-docx \u53d6\u6bb5\u843d\uff1bpptx \u6309\u9875\u62fc\u5e7b\u706f\u7247\u6587\u5b57\uff1bxlsx \u7528 openpyxl \u8bfb\u8868\u3002"),
    bullet("\u51c0\u5316\uff1a\u53bb\u63a7\u5236\u5b57\u7b26\u3001\u538b\u7f29\u7a7a\u767d\u3001\u53bb\u6389\u8fc7\u957f\u7684\u91cd\u590d\u884c\u3002"),
    bullet("\u53bb\u91cd\uff1aSHA-256(\u6e05\u6d17\u6b63\u6587)\uff0c\u76f8\u540c\u54c8\u5e0c\u8fd4\u56de status=duplicate\u3002"),
    bullet("\u7d22\u5f15\uff1aindex.json + documents/<id>.txt\u3002"),
    bullet("\u68c0\u7d22\uff1a\u4e2d\u6587\u5355\u5b57 + \u53cc\u5b57\u6ed1\u7a97 + \u82f1\u6587\u5355\u8bcd\uff0c\u6309\u547d\u4e2d\u6b21\u6570\u8bc4\u5206\uff0c\u8fd4\u56de snippet \u5f15\u7528\u3002"),
    h2("7.3 能做到什么程度"),
    p("\u80fd\uff1a\u628a\u89c4\u8303\u3001\u4f1a\u8bae\u7eaa\u8981\u3001\u4ea7\u54c1\u8bf4\u660e\u53d8\u6210\u53ef\u68c0\u7d22\u77e5\u8bc6\uff1b\u5bf9\u8bdd\u91cc\u51fa\u73b0\u201c\u6587\u6863/\u8d44\u6599/\u77e5\u8bc6\u5e93\u201d\u7b49\u8bcd\u65f6\u81ea\u52a8\u68c0\u7d22\u5e76\u628a\u5f15\u7528\u8d34\u5728\u56de\u7b54\u4e0b\u65b9\u3002\u4e0d\u80fd\uff1aOCR \u626b\u63cf\u7248 PDF\u3001\u590d\u6742\u8868\u683c\u7ed3\u6784\u4fdd\u771f\u3001\u8bed\u4e49\u76f8\u4f3c\u4f46\u7528\u8bcd\u4e0d\u540c\u7684\u6df1\u5ea6\u68c0\u7d22\u3001\u591a\u7528\u6237\u79c1\u6709\u77e5\u8bc6\u5e93\u9694\u79bb\uff08\u5f53\u524d\u77e5\u8bc6\u5e93\u662f\u5168\u5c40\u5171\u4eab\u7684\uff09\u3002"),

    h1("8. 项目秘书 secretary_runtime 与现实补丁"),
    h2("8.1 目标"),
    p("\u628a\u4f1a\u8bdd\u91cc\u7684\u201c\u6211\u4eec\u8981\u505a\u4ec0\u4e48\u201d\u53d8\u6210\u770b\u677f\u4e0a\u7684\u4efb\u52a1\uff0c\u4f46\u7edd\u4e0d\u8df3\u8fc7\u4eba\u5de5\u786e\u8ba4\u3002\u8fd9\u662f\u4e3a\u4e86\u907f\u514d Agent \u81ea\u4f5c\u4e3b\u5f20\u628a\u9519\u8bef\u4efb\u52a1\u5199\u8fdb\u771f\u5b9e\u9879\u76ee\u3002"),
    h2("8.2 技术实现"),
    bullet("\u5b9e\u4f53\uff1aprojects\u3001tasks\u3001sync_sessions\u3001patches\u3001audit_events\u3002"),
    bullet("\u4efb\u52a1\u72b6\u6001\uff1atodo / in_progress / blocked / done\u3002"),
    bullet("\u8865\u4e01\u72b6\u6001\uff1adraft \u2192 applied \u2192 rolled_back\u3002\u786e\u8ba4\u65f6\u5199 rollback_data\uff0c\u56de\u6eda\u6309\u5b83\u6062\u590d\u3002"),
    bullet("\u5bf9\u8bdd\u89e6\u53d1\uff1a\u542b\u201c\u521b\u5efa/\u65b0\u589e\u4efb\u52a1\u201d\u751f\u6210 create \u8865\u4e01\uff1b\u542b\u201c\u540c\u6b65\u4efb\u52a1/\u4f1a\u8bae\u7eaa\u8981\u201d\u751f\u6210\u540c\u6b65\u8349\u7a3f\u3002"),
    bullet("\u786e\u8ba4\u540c\u6b65\u4f1a\u4ece\u8349\u7a3f JSON \u6279\u91cf\u63d2\u5165 tasks\u3002"),
    h2("8.3 能做到什么程度"),
    p("\u80fd\uff1a\u4e00\u4efd\u770b\u677f\u3001\u8865\u4e01\u6d41\u6c34\u3001\u786e\u8ba4\u540e\u771f\u6b63\u5efa\u4efb\u52a1\u3001\u56de\u6eda\u5220\u9664\u8bef\u5efa\u4efb\u52a1\u3001\u5ba1\u8ba1\u8ddf\u8e2a\u8c01\u70b9\u7684\u786e\u8ba4\u3002\u4e0d\u80fd\uff1a\u81ea\u52a8\u6309\u4eba\u8ba4\u9886\u3001\u90ae\u4ef6/\u9489\u9489\u63a8\u9001\u3001GitHub \u53cc\u5411\u540c\u6b65\uff08\u67b6\u6784\u6587\u6863\u91cc\u5199\u4e86\u613f\u666f\u4f46\u4ee3\u7801\u5c1a\u672a\u843d\u5730\uff09\u3001\u7ec6\u7c92\u5ea6\u4eba\u5458\u6743\u9650\u3002\u79d8\u4e66\u5e93\u662f\u5de5\u4f5c\u533a\u7ea7\u5171\u4eab\uff0c\u4e0d\u662f\u6309\u7528\u6237\u5206\u5e93\u3002"),

    h1("9. 核心编排 unified_agent"),
    h2("9.1 protocol.py：统一信封"),
    p("InteractionEnvelope \u662f\u5165\u53e3\u552f\u4e00\u683c\u5f0f\uff1auser_id\u3001channel\u3001message\u3001conversation_id\u3001workspace_id\u3001attachments\u3001timestamp\u3001permissions\u3001context\u3002ResponseEnvelope \u662f\u51fa\u53e3\u552f\u4e00\u683c\u5f0f\uff1acontent\u3001citations\u3001memory_events\u3001secretary_events\u3001tips\u3001requires_confirmation\u3001audit_id\u3002QQ \u548c Web \u90fd\u7528\u8fd9\u4e00\u5957\uff0c\u4ee5\u514d\u4e24\u5957\u903b\u8f91\u3002"),
    h2("9.2 core.py：调度顺序"),
    p("1) \u6821\u9a8c message \u975e\u7a7a\uff1b2) \u6784\u5efa\u7528\u6237\u8bb0\u5fc6\u4e0a\u4e0b\u6587\uff1b3) \u82e5\u50cf\u67e5\u77e5\u8bc6\u5e93\u5219 search_library\uff1b4) \u82e5\u50cf\u540c\u6b65\u5219 draft_sync\uff0c\u82e5\u50cf\u5efa\u4efb\u52a1\u5219 create_patch\uff1b5) \u8c03 LLM\uff1b6) record_interaction \u843d\u5730\u8bb0\u5fc6\uff1b7) TipEngine.evaluate\uff1b8) \u88c5\u914d citations \u4e0e secretary_events \u8fd4\u56de\u3002"),
    h2("9.3 llm.py：模型层"),
    p("\u9ed8\u8ba4 BASE_URL=https://api.deepseek.com\uff0c\u6a21\u578b deepseek-v4-flash\u3002\u7528 urllib \u53d1 Chat Completions\u3002system prompt \u4f1a\u6ce8\u5165\u3010\u957f\u671f\u7528\u6237\u8bb0\u5fc6\u3011\u548c\u3010\u672c\u5730\u77e5\u8bc6\u5e93\u53c2\u8003\u3011\u3002\u8d85\u65f6\u6216\u65ad\u7f51\u8d70 fallback_responder\uff1a\u6709\u77e5\u8bc6\u5e93\u5c31\u76f4\u63a5\u8d34\u7247\u6bb5\uff0c\u6709\u8bb0\u5fc6\u5c31\u63d0\u4e00\u53e5\u7ed3\u5408\u504f\u597d\uff0c\u5426\u5219\u56de\u663e\u201c\u6211\u5df2\u6536\u5230\u201d\u3002\u8fd9\u4fdd\u8bc1\u6ca1\u6709\u94b1\u6216\u6ca1\u7f51\u65f6\uff0c\u8bb0\u5fc6\u548c\u8865\u4e01\u6d41\u7a0b\u4ecd\u80fd\u9a8c\u8bc1\u3002"),

    h1("10. Tip 引擎与认知引擎"),
    h2("10.1 tip_engine"),
    p("\u5b83\u4e0d\u6539\u5199\u4e3b\u56de\u7b54\uff0c\u53ea\u5728\u65c1\u8fb9\u8d34\u4e00\u5f20\u53ef\u5173\u95ed\u5361\u7247\u3002\u89c4\u5219\u4f8b\u5b50\uff1a\u8fde\u7eed\u4e09\u6b21\u8bf4\u540c\u4e00\u53e5\u2192\u5efa\u8bae\u6362\u6210\u6700\u5c0f\u53ef\u884c\u52a8\uff1b\u957f\u6587\u6ca1\u6709\u201c\u56e0\u4e3a/\u6765\u6e90/\u6570\u636e\u201d\u2192\u5efa\u8bae\u8865\u8bc1\u636e\uff1b\u5df2\u6709\u98ce\u9669\u5374\u8bf4\u201c\u5148\u4e0d\u7ba1\u201d\u2192\u5efa\u8bae\u7ed9\u8d1f\u8d23\u4eba\u3002\u9ed8\u8ba4 900 \u79d2\u51b7\u5374\uff0c\u907f\u514d\u5237\u5c4f\u3002"),
    h2("10.2 cognitive_engine"),
    p("PythonCognitiveEngine \u63d0\u4f9b analyze\uff08\u8bcd\u6570/\u65b0\u9896\u5ea6\uff09\u3001score_feedback\uff08confirm +0.1\u3001reject -0.2\uff09\u3001detect_direction_shift\u3001update_relationship\u3002\u53ef\u901a\u8fc7 COGNITIVE_ENGINE_LIBRARY \u6302 C++ DLL\uff08ctypes\uff09\u3002C++ \u4e0d\u5f97\u62e5\u6709 LLM \u8c03\u7528\u548c\u6570\u636e\u5e93\u5199\u5165\uff0c\u53ea\u505a\u8ba1\u7b97\u3002\u7f3a\u5e93\u65f6 Python \u5b8c\u6574\u53ef\u7528\u3002"),

    h1("11. 入口层：app.py、前端、QQ、一键启动"),
    h2("11.1 app.py"),
    p("Flask \u6302\u8f7d\u9759\u6001\u76ee\u5f55 static\u3002\u542f\u52a8\u65f6 load_dotenv\u3002get_current_user \u89e3\u6790 Bearer \u6216 ?token=\u3002@require_auth \u8fd4 401\uff0c@require_admin \u8fd4 403\u3002\u4ea4\u4e92\u63a5\u53e3\u5728\u767b\u5f55\u540e\u9501\u5b9a user_id\u3002/qq \u628a OneBot message \u8f6c\u6210 InteractionEnvelope\u3002\u9ed8\u8ba4 127.0.0.1:8091\u3002"),
    h2("11.2 前端控制台"),
    p("\u5355\u6587\u4ef6 static/index.html\u3002\u56db\u4e2a\u6807\u7b7e\u9875\uff1a\u667a\u80fd\u4ea4\u4e92\u3001\u79d8\u4e66\u770b\u677f\u3001\u77e5\u8bc6\u5e93\u3001\u7528\u6237\u8bb0\u5fc6\u3002\u672a\u767b\u5f55\u906e\u7f69\u767b\u5f55/\u6ce8\u518c\u3002Token \u5b58 localStorage\u3002\u7ba1\u7406\u5458\u53ef\u89c1\u5168\u7528\u6237\u753b\u50cf\u9762\u677f\u3002Markdown \u7528 marked.js \u6e32\u67d3\u3002\u8be6\u7ec6\u524d\u7aef\u8c03\u7528\u89c1\u53e6\u4e00\u4efd\u300a\u524d\u7aef\u63a7\u5236\u53f0\u63a5\u53e3\u6587\u6863\u300b\u3002"),
    h2("11.3 start.bat"),
    p("ANSI \u7f16\u7801\u7684 CMD \u811a\u672c\uff0c\u907f\u514d UTF-8 \u4e2d\u6587\u6ce8\u91ca\u628a Windows \u63a7\u5236\u53f0\u6253\u5d29\u3002\u5b83\u4f1a\u627e py -3 \u6216 python\uff0c\u542f\u52a8 app.py\uff0c\u5e76\u5728 2 \u79d2\u540e\u6253\u5f00\u9ed8\u8ba4\u6d4f\u89c8\u5668\u3002"),
    h2("11.4 adapters"),
    p("\u751f\u4ea7\u73af\u5883\u7684 NapCat \u5e94\u53ea\u8f6c\u4fe1\u5c01\uff0c\u4e0d\u76f4\u63a5\u8bfb memory.sqlite3\u3002legacy_adapter.py \u7528\u4e8e\u5bf9\u63a5\u65e7\u9879\u76ee\u51fd\u6570\u540d\uff0c\u539f\u4ed3\u5e93\u4e0d\u6539\u3002"),

    h1("12. 权限模型与安全边界"),
    caption("\u8868 3  \u89d2\u8272\u80fd\u529b\u77e9\u9635"),
    table(
      ["\u80fd\u529b", "\u672a\u767b\u5f55", "\u666e\u901a\u7528\u6237", "\u7ba1\u7406\u5458"],
      [
        ["\u6ce8\u518c/\u767b\u5f55", "\u53ef", "\u53ef", "\u53ef"],
        ["\u5bf9\u8bdd/\u77e5\u8bc6\u5e93/\u770b\u677f", "\u53ef\uff08user_id \u53ef\u88ab\u4f2a\u9020\uff09", "\u53ef\uff0c\u8bb0\u5fc6\u5199\u81ea\u8eab", "\u53ef"],
        ["\u67e5\u81ea\u8eab\u8bb0\u5fc6", "\u53ef\u6309\u8def\u5f84\u67e5", "\u53ef", "\u53ef"],
        ["\u67e5\u4ed6\u4eba\u8bb0\u5fc6", "\u65e0\u9274\u6743\u65f6\u4ecd\u53ef\u80fd", "403", "\u53ef"],
        ["/v1/admin/*", "401", "403", "\u53ef"],
      ],
      [28, 24, 24, 24]
    ),
    p("\u9700\u8981\u77e5\u9053\u7684\u9650\u5236\uff1a\u5bf9\u8bdd\u4e0e\u77e5\u8bc6\u5e93\u63a5\u53e3\u76ee\u524d\u4e0d\u5f3a\u5236\u767b\u5f55\uff0c\u4ee5\u517c\u5bb9\u65e7\u6d4b\u8bd5\u4e0e QQ\u3002\u4e00\u65e6\u5e26 Token\uff0cuser_id \u5c31\u88ab\u9501\u6b7b\u3002\u524d\u7aef\u4f1a\u5f3a\u5236\u5148\u767b\u5f55\u3002\u8fd9\u662f\u201c\u4ea7\u54c1\u63a7\u5236\u53f0\u5fc5\u767b + API \u4ecd\u53ef\u672c\u5730\u8c03\u8bd5\u201d\u7684\u6298\u4e2d\u3002"),

    h1("13. 端到端使用路径（照着点就会）"),
    bullet("\u53cc\u51fb start.bat\uff0c\u7b49\u6d4f\u89c8\u5668\u6253\u5f00 http://127.0.0.1:8091/\u3002"),
    bullet("\u70b9\u767b\u5f55\uff1aadmin / admin123 \u6216 alice / 123456\u3002\u4e0d\u8981\u7528\u5df2\u5b58\u5728\u8d26\u53f7\u53bb\u70b9\u6ce8\u518c\u3002"),
    bullet("\u5728\u5bf9\u8bdd\u91cc\u8bf4\u201c\u6211\u5e73\u65f6\u6700\u559c\u6b22\u559d\u62ff\u94c1\u5496\u5561\u201d\uff0c\u5207\u5230\u8bb0\u5fc6\u9875\u770b\u753b\u50cf\u3002"),
    bullet("\u5728\u77e5\u8bc6\u5e93\u4e0a\u4f20\u4e00\u4efd md/\u6587\u672c\uff0c\u518d\u95ee\u201c\u8bf7\u67e5\u9605\u77e5\u8bc6\u5e93\u6587\u6863\u8d44\u6599\u2026\u201d\u3002"),
    bullet("\u8bf4\u201c\u521b\u5efa\u4e00\u4e2a\u4efb\u52a1\uff1a\u5b8c\u6210\u8054\u8c03\u201d\uff0c\u5728\u6c14\u6ce1\u6216\u770b\u677f\u91cc\u786e\u8ba4\u8865\u4e01\uff0c\u518d\u56de\u6eda\u770b\u4efb\u52a1\u662f\u5426\u6d88\u5931\u3002"),
    bullet("\u7528 alice \u767b\u5f55\u65f6\u4e0d\u4f1a\u51fa\u73b0\u5168\u7528\u6237\u753b\u50cf\u9762\u677f\uff1b\u6362 admin \u5219\u53ef\u4ee5\u5207\u6362\u67e5 alice / bob\u3002"),

    h1("14. 测试、质量与已知边界"),
    p("tests/ \u4e0b\u542b API \u5065\u5eb7\u68c0\u67e5\u3001\u8bb0\u5fc6\u9694\u79bb\u3001\u6587\u4ef6\u4e0a\u4f20400\u3001\u8865\u4e01\u786e\u8ba4\u4e0e\u56de\u6eda\u3001\u8ba4\u8bc1\u8d8a\u6743 403 \u7b49\u7528\u4f8b\u3002\u53ef\u8dd1 python -m unittest discover -s tests -v\u3002"),
    p("\u5df2\u77e5\u8fb9\u754c\uff1a1) \u77e5\u8bc6\u5e93\u5168\u5c40\u5171\u4eab\uff0c\u4e0d\u662f\u6bcf\u4eba\u4e00\u5ea7\u79c1\u6709\u9986\uff1b2) \u79d8\u4e66\u5e93\u6309\u5de5\u4f5c\u533a\u5171\u4eab\uff1b3) \u8bb0\u5fc6\u63d0\u53d6\u4f9d\u8d56\u4e2d\u6587\u53e3\u8bed\u6b63\u5219\uff1b4) LLM \u6d41\u5f0f\u63a5\u53e3\u5b9e\u9645\u662f\u4e00\u6b21\u6027 JSON \u88c5\u6210 SSE\uff0c\u4e0d\u662f token \u7ea7\u6253\u5b57\uff1b5) Flask \u5f00\u53d1\u670d\u52a1\u5668\u4e0d\u9002\u5408\u516c\u7f51\u66b4\u9732\uff1b6) \u9ed8\u8ba4\u7ba1\u7406\u5458\u5bc6\u7801\u5e94\u5728\u771f\u5b9e\u90e8\u7f72\u65f6\u6539\u6389\u3002"),

    h1("15. 和“大而全 Agent 产品”差在哪里"),
    p("\u8fd9\u4e2a\u9879\u76ee\u7684\u4ef7\u503c\u4e0d\u662f\u5806\u53e0\u6700\u591a\u63d2\u4ef6\uff0c\u800c\u662f\u628a\u56db\u6761\u4ea7\u54c1\u539f\u5219\u843d\u5b9e\u6210\u53ef\u8dd1\u4ee3\u7801\uff1a\u4e00\u4e2a\u6838\u5fc3\u591a\u6e20\u9053\uff1b\u7528\u6237\u8bb0\u5fc6\u7269\u7406\u9694\u79bb\uff1b\u73b0\u5b9e\u53d8\u66f4\u5fc5\u987b\u8865\u4e01\u786e\u8ba4\uff1b\u77e5\u8bc6\u5fc5\u987b\u53ef\u5f15\u7528\u3002\u5b83\u9002\u5408\u5f53\u4f5c\u5b66\u4e60\u6837\u677f\u3001\u672c\u5730\u52a9\u624b\u548c\u4e8c\u6b21\u5f00\u53d1\u5e95\u5ea7\u3002\u82e4\u82e4\u628a\u5b83\u5f53\u4f01\u4e1a IM \u5e73\u53f0\u6216\u4e07\u4eba SaaS\uff0c\u5c31\u4f1a\u5931\u671b\u3002"),
    p("\u82e5\u8981\u7ee7\u7eed\u52a0\u539a\uff0c\u81ea\u7136\u4e0b\u4e00\u6b65\u662f\uff1a\u77e5\u8bc6\u5e93\u6309\u7528\u6237/\u56e2\u961f\u5206\u5e93\u3001\u5411\u91cf\u68c0\u7d22\u3001\u771f\u6b63 token \u6d41\u5f0f\u3001\u5f3a\u5236\u5168\u90e8 API \u767b\u5f55\u3001\u8865\u4e01\u5bf9\u63a5\u5916\u90e8\u7968\u636e/\u65e5\u5386\u3002\u73b0\u6709\u4ee3\u7801\u5df2\u7ecf\u628a\u8fd9\u4e9b\u63a5\u53e3\u9762\u7559\u5728\u4fe1\u5c01\u548c\u72b6\u6001\u673a\u91cc\u3002"),

    h1("16. 术语表"),
    table(
      ["\u672f\u8bed", "\u4eba\u8bdd"],
      [
        ["Envelope / \u4fe1\u5c01", "\u628a\u8bf7\u6c42\u6216\u56de\u590d\u88c5\u6210\u56fa\u5b9a\u5b57\u6bb5\u7684\u4e00\u4e2a JSON \u76d2\u5b50"],
        ["Runtime", "\u4e00\u4e2a\u72ec\u7acb\u8dd1\u7684\u4e1a\u52a1\u6a21\u5757"],
        ["RealityPatch", "\u5bf9\u771f\u5b9e\u4efb\u52a1/\u51b3\u7b56\u7684\u5f85\u786e\u8ba4\u53d8\u66f4\u5355"],
        ["Citation", "\u56de\u7b54\u4f9d\u636e\u7684\u6587\u6863\u7247\u6bb5"],
        ["Bearer Token", "\u653e\u5728 Authorization \u5934\u91cc\u7684\u767b\u5f55\u51ed\u8bc1"],
        ["SSE", "\u670d\u52a1\u5668\u9010\u6bb5\u628a\u4e8b\u4ef6\u63a8\u7ed9\u6d4f\u89c8\u5668\u7684\u6280\u672f"],
        ["Fallback", "\u4e3b\u8def\u5f84\u5931\u8d25\u65f6\u8d70\u7684\u5907\u7528\u8def\u5f84"],
      ],
      [28, 72]
    ),
  ];
}

function apiDocBody() {
  const apis = [
    ["\u767b\u5f55\u8868\u5355\u63d0\u4ea4", "POST", "/v1/auth/login", "Public", "\u8fd4 token + user"],
    ["\u6ce8\u518c\u8868\u5355\u63d0\u4ea4", "POST", "/v1/auth/register", "Public", "\u53ea\u80fd\u6ce8 user"],
    ["\u6253\u5f00\u9875\u9762\u6062\u590d\u767b\u5f55", "GET", "/v1/auth/me", "Auth", "\u5931\u6548\u5219\u56de\u767b\u5f55\u5c42"],
    ["\u70b9\u9000\u51fa", "POST", "/v1/auth/logout", "Auth", "\u5220\u4ee4\u724c"],
    ["\u53d1\u9001\u5bf9\u8bdd\uff08\u666e\u901a\uff09", "POST", "/v1/interactions", "Auth \u5efa\u8bae", "\u9501 user_id"],
    ["\u53d1\u9001\u5bf9\u8bdd\uff08SSE \u5f00\u5173\uff09", "POST", "/v1/interactions/stream", "Auth \u5efa\u8bae", "data: response/done"],
    ["\u5237\u65b0\u770b\u677f", "GET", "/v1/workspaces/{id}/dashboard", "Public", "tasks+patches"],
    ["\u786e\u8ba4\u8865\u4e01", "POST", "/v1/patches/{id}/confirm", "Auth \u5efa\u8bae", "draft\u2192applied"],
    ["\u56de\u6eda\u8865\u4e01", "POST", "/v1/patches/{id}/rollback", "Auth \u5efa\u8bae", "applied\u2192rolled_back"],
    ["\u786e\u8ba4\u540c\u6b65\u8349\u7a3f", "POST", "/v1/sync/{sid}/confirm", "Auth \u5efa\u8bae", "\u6279\u91cf\u5efa\u4efb\u52a1"],
    ["\u6587\u6863\u5217\u8868", "GET", "/v1/library/documents", "Public", "index.json"],
    ["\u62d6\u62fd\u4e0a\u4f20\u6587\u4ef6", "POST", "/v1/library/documents", "Public", "multipart file"],
    ["\u624b\u5de5\u5f55\u5165\u6587\u672c", "POST", "/v1/library/documents", "Public", "JSON content"],
    ["\u77e5\u8bc6\u5e93\u641c\u7d22\u6846", "GET", "/v1/library/search?q=", "Public", "\u53cc\u5b57\u6253\u5206"],
    ["\u8bb0\u5fc6\u753b\u50cf\u5217\u8868", "GET", "/v1/users/{uid}/memory", "Auth", "\u8de8\u7528\u6237 403"],
    ["\u70b9\u8d5e/\u8e29", "POST", "/v1/feedback", "Auth \u5efa\u8bae", "confirm/reject"],
    ["\u9057\u5fd8\u8bb0\u5fc6", "POST", "/v1/users/{uid}/memory/{mid}/forget", "Auth", "\u6574\u6761 evidence"],
    ["\u7ba1\u7406\u5458\u7528\u6237\u5361\u7247", "GET", "/v1/admin/users", "Admin", "\u7edf\u8ba1\u6982\u89c8"],
    ["\u7ba1\u7406\u5458\u7a7f\u900f\u753b\u50cf", "GET", "/v1/admin/users/{uid}/profile", "Admin", "\u5b8c\u6574 memories"],
    ["\u9876\u90e8\u5065\u5eb7\u706f", "GET", "/health", "Public", "\u5f15\u64ce\u540d"],
  ];

  return [
    h1("1. 文档目的与读者"),
    p("\u672c\u6587\u6863\u4e13\u95e8\u5199\u7ed9\u524d\u7aef\u63a7\u5236\u53f0\uff08static/index.html\uff09\u3002\u5b83\u4e0d\u91cd\u590d\u8bb2\u67b6\u6784\u539f\u7406\uff0c\u800c\u662f\u628a\u201c\u9875\u9762\u4e0a\u6bcf\u4e00\u4e2a\u6309\u94ae\u3001\u8868\u5355\u3001\u5f00\u5173\u201d\u6620\u5c04\u5230\u540e\u7aef HTTP \u63a5\u53e3\uff1a\u8c01\u53d1\u3001\u53d1\u4ec0\u4e48\u3001\u5e26\u4e0d\u5e26 Token\u3001\u6210\u529f\u540e\u9875\u9762\u600e\u4e48\u53d8\u3002\u5f00\u53d1\u8005\u53ef\u6309\u7167\u672c\u8868\u8054\u8c03\uff1b\u4ea7\u54c1\u53ef\u7528\u672c\u8868\u505a\u9a8c\u6536\u3002"),
    p("\u57fa\u5730\u5740\uff1ahttp://127.0.0.1:8091 \u3002\u9274\u6743\u5934\uff1aAuthorization: Bearer <token>\u3002Token \u5b58\u5728\u6d4f\u89c8\u5668 localStorage.myagent_token\u3002\u524d\u7aef\u7edf\u4e00\u51fd\u6570 authHeaders() \u4f1a\u81ea\u52a8\u9644\u52a0\u8be5\u5934\u3002"),

    h1("2. 页面结构与状态机"),
    h2("2.1 全局 state"),
    codeBlock("activeTab, userId, workspaceId, isStreaming, token, currentUser, authMode"),
    p("userId \u5728\u666e\u901a\u7528\u6237\u4e0b\u7b49\u4e8e\u767b\u5f55\u540d\uff1b\u7ba1\u7406\u5458\u53ef\u901a\u8fc7\u753b\u50cf\u76ee\u6807\u4e0b\u62c9\u6846\u6539\u6210\u5176\u4ed6\u7528\u6237\u540d\uff0c\u4ec5\u7528\u4e8e\u67e5\u770b\u8bb0\u5fc6\uff0c\u4e0d\u6539\u53d8\u767b\u5f55\u8eab\u4efd\u3002"),
    h2("2.2 登录遮罩"),
    p("id=authOverlay\u3002\u65e0 token \u6216 /v1/auth/me 5931 \u65f6\u663e\u793a\u3002\u767b\u5f55\u6210\u529f\u540e hidden\u3002\u6ce8\u518c\u6210\u529f\u4e0d\u76f4\u63a5\u8fdb\u63a7\u5236\u53f0\uff0c\u800c\u662f\u7acb\u523b\u518d\u8c03\u4e00\u6b21 login\u3002\u975e JSON\uff08\u4f8b\u5982\u65e7\u8fdb\u7a0b 404 HTML\uff09\u4f1a\u663e\u793a\u201c\u8ba4\u8bc1\u63a5\u53e3\u4e0d\u5b58\u5728\uff0c\u8bf7\u91cd\u542f\u540e\u7aef\u201d\u3002"),
    h2("2.3 四个标签页"),
    table(
      ["tabId", "\u9875\u9762", "\u8fdb\u5165\u65f6\u52a0\u8f7d"],
      [
        ["chat", "\u667a\u80fd\u4ea4\u4e92\u5de5\u4f5c\u53f0", "\u65e0"],
        ["kanban", "\u79d8\u4e66\u770b\u677f\u4e0e\u8865\u4e01", "loadDashboard()"],
        ["library", "\u6587\u6863\u77e5\u8bc6\u5e93", "loadLibrary()"],
        ["memory", "\u7528\u6237\u8bb0\u5fc6\u4e0e\u753b\u50cf", "loadUserMemories()\uff1badmin \u518d loadAdminUsers()"],
      ],
      [18, 28, 54]
    ),

    h1("3. 界面操作到接口总表"),
    caption("\u8868 1  \u63a7\u5236\u53f0\u64cd\u4f5c\u4e0e HTTP \u6620\u5c04"),
    table(["\u754c\u9762\u52a8\u4f5c", "\u65b9\u6cd5", "\u8def\u5f84", "\u6743\u9650", "\u8bf4\u660e"], apis, [22, 10, 30, 16, 22]),

    h1("4. 认证接口（登录层）"),
    h2("4.1 POST /v1/auth/register"),
    p("\u8bf7\u6c42 JSON\uff1ausername\uff08\u22653\uff09\u3001password\uff08\u22656\uff09\u3001nickname \u53ef\u9009\u3002\u6210\u529f 200 {success,user}\u3002\u91cd\u540d 400\u3002\u524d\u7aef\u5728\u6ce8\u518c\u6210\u529f\u540e\u7acb\u523b login\u3002"),
    h2("4.2 POST /v1/auth/login"),
    p("\u8bf7\u6c42 JSON\uff1ausername, password\u3002\u6210\u529f\u8fd4 token\u3001expires_at\u3001user{id,username,role,nickname}\u3002\u524d\u7aef applySession \u5199 localStorage\u3001\u9690\u85cf\u906e\u7f69\u3001\u663e\u793a\u89d2\u8272\u5fbd\u7ae0\u3002role=admin \u65f6\u6253\u5f00\u753b\u50cf\u4e0b\u62c9\u6846\u4e0e\u5168\u7528\u6237\u9762\u677f\u3002"),
    h2("4.3 GET /v1/auth/me"),
    p("\u4ec5 Bearer\u3002\u7528\u4e8e\u5237\u65b0\u9875\u9762\u6062\u590d\u4f1a\u8bdd\u3002401 \u5219 clearSession\u3002"),
    h2("4.4 POST /v1/auth/logout"),
    p("\u5220\u670d\u52a1\u7aef tokens \u884c\uff0c\u524d\u7aef\u6e05 localStorage \u5e76\u6253\u5f00\u767b\u5f55\u5c42\u3002"),
    codeBlock('{"username":"alice","password":"123456"}'),
    codeBlock('{"token":"tok_...","user":{"username":"alice","role":"user"}}'),

    h1("5. 智能交互工作台"),
    h2("5.1 发送消息"),
    p("\u8868\u5355 id=chatForm\u3002payload \u56fa\u5b9a channel=web\uff0cuser_id=state.userId\uff0cworkspace_id=state.workspaceId\u3002isStreaming=true \u8d70 /v1/interactions/stream\uff0c\u5426\u5219 /v1/interactions\u3002\u8bf7\u6c42\u5934\u5e26 Content-Type \u4e0e Bearer\u3002"),
    h3("5.1.1 同步响应字段如何渲染"),
    bullet("content \u2192 marked.parse \u8fdb agent-content\u3002"),
    bullet("secretary_events.type=reality_patch \u2192 \u6c14\u6ce1\u5185\u786e\u8ba4\u6309\u94ae\uff0c\u8c03 confirmPatch\u3002"),
    bullet("secretary_events.type=sync_draft \u2192 \u4e00\u952e\u786e\u8ba4\u540c\u6b65\uff0c\u8c03 confirmSync\u3002"),
    bullet("citations \u2192 \u77e5\u8bc6\u5e93\u6765\u6e90\u5361\u3002"),
    bullet("tips \u2192 \u9ec4\u8272\u542f\u53d1\u5f0f\u63d0\u793a\u5361\u3002"),
    bullet("memory_events \u2192 \u5e95\u90e8\u7070\u8272\u201c\u8403\u53d6\u957f\u671f\u8bb0\u5fc6\u201d\u3002"),
    h3("5.1.2 SSE 事件"),
    p("\u6bcf\u884c data: JSON\\n\\n\u3002type=response \u65f6 data \u4e3a\u5b8c\u6574 ResponseEnvelope\uff1btype=done \u7ed3\u675f\uff1btype=error \u663e\u7ea2\u5b57\u3002\u5f53\u524d\u5b9e\u73b0\u662f\u4e00\u6b21\u6027\u63a8\u9001\u6574\u5305\uff0c\u4e0d\u662f\u9010 token\u3002"),
    h2("5.2 快捷芯片"),
    p("fillChatInput \u53ea\u6539\u8f93\u5165\u6846\uff0c\u4e0d\u53d1\u63a5\u53e3\u3002\u793a\u4f8b\uff1a\u8bb0\u4e60\u60ef\u3001\u62df\u5b9a\u4efb\u52a1\u8865\u4e01\u3001\u77e5\u8bc6\u5e93\u68c0\u7d22\u3001\u6279\u91cf\u540c\u6b65\u8349\u7a3f\u3002"),

    h1("6. 秘书看板与补丁"),
    h2("6.1 GET /v1/workspaces/{workspace_id}/dashboard"),
    p("workspace_id \u53d6\u9876\u90e8\u8f93\u5165\u6846\u3002\u54cd\u5e94 counts \u5237\u65b0\u56db\u5f20\u7edf\u8ba1\u5361\u4e0e\u6cf3\u9053\u5fbd\u7ae0\uff1btasks \u6309 status \u5206\u5230 Todo/In Progress/Blocked/Done\uff1bpatches \u586b\u8865\u4e01\u8868\u3002status=draft \u663e\u201c\u786e\u8ba4\u5e94\u7528\u201d\uff1bapplied \u663e\u201c\u56de\u6eda\u201d\u3002"),
    h2("6.2 POST /v1/patches/{id}/confirm"),
    p("body {actor:state.userId}\u3002\u6210\u529f alert \u5e76 loadDashboard\u3002409 \u4e3a\u975e\u8349\u7a3f\u72b6\u6001\u3002"),
    h2("6.3 POST /v1/patches/{id}/rollback"),
    p("\u5148 window.confirm\u3002\u6210\u529f\u540e\u4efb\u52a1\u5e94\u6309 rollback_data \u6d88\u5931\u6216\u6062\u590d\u3002"),
    h2("6.4 POST /v1/sync/{session_id}/confirm"),
    p("\u5bf9\u8bdd\u91cc\u540c\u6b65\u8349\u7a3f\u5361\u7247\u89e6\u53d1\u3002\u6210\u529f\u8fd4 tasks[]\uff0c\u63d0\u793a\u65b0\u589e\u6761\u6570\u3002"),

    h1("7. 文档知识库页"),
    h2("7.1 GET /v1/library/documents"),
    p("\u6e32\u67d3\u6587\u6863\u5361\uff1atitle\u3001source\u3001content \u6458\u8981\u3001content_hash \u524d 16 \u4f4d\u3001char_count\u3002"),
    h2("7.2 POST /v1/library/documents \u6587\u4ef6"),
    p("FormData: file + source=upload\u3002\u4e0d\u8981\u624b\u5199 Content-Type\uff0c\u8ba9\u6d4f\u89c8\u5668\u5e26 boundary\u3002\u652f\u6301 pdf/docx/pptx/xlsx/md/txt/csv/json\u3002\u4e0d\u652f\u6301\u6269\u5c55\u540d 400\u3002duplicate \u65f6 status=duplicate\u3002"),
    h2("7.3 POST /v1/library/documents JSON"),
    p("{filename, content, source:'manual'}\u3002\u7a7a\u5185\u5bb9\u524d\u7aef\u62e6\u622a\u3002"),
    h2("7.4 GET /v1/library/search"),
    p("q \u4e3a\u641c\u7d22\u6846\uff0climit=10\u3002\u7ed3\u679c\u66ff\u6362\u5217\u8868\u4e3a\u547d\u4e2d\u7247\u6bb5 + score\u3002"),

    h1("8. 用户记忆与画像页"),
    h2("8.1 GET /v1/users/{user_id}/memory"),
    p("user_id=state.userId\uff0c\u53ef\u5e26 q\u3001limit=50\u3002\u5361\u7247\u5c55\u793a category\u3001confidence%\u3001content\u3001evidence\u3001occurrence_count\u3002401 \u56de\u767b\u5f55\uff1b403 \u7ea2\u5b57\u63d0\u793a\u65e0\u6743\u3002"),
    h2("8.2 POST /v1/feedback"),
    p("{user_id, memory_id, feedback_type:'confirm'|'reject'}\u3002\u6210\u529f\u540e\u91cd\u8bf7\u5217\u8868\u3002"),
    h2("8.3 POST /v1/users/{user_id}/memory/{memory_id}/forget"),
    p("\u786e\u8ba4\u5bf9\u8bdd\u540e\u8c03\u7528\u3002success=true \u5219\u5237\u65b0\u3002"),
    h2("8.4 管理员面板"),
    p("GET /v1/admin/users \u6e32\u67d3\u7528\u6237\u5361\u4e0e\u4e0b\u62c9\u6846\u3002inspectUser(username) \u6539 state.userId \u518d loadUserMemories\u3002GET /v1/admin/users/{id}/profile \u53ef\u5728\u540e\u7aef\u76f4\u63a5\u7528\uff0c\u5f53\u524d\u9875\u9762\u4e3b\u8981\u7528\u5217\u8868+memory \u7ec4\u5408\u8fbe\u5230\u540c\u6837\u76ee\u7684\u3002"),

    h1("9. 统一请求/响应信封"),
    h2("9.1 InteractionEnvelope \u8bf7\u6c42\u4f8b"),
    codeBlock('{"user_id":"alice","channel":"web","workspace_id":"default","message":"\u6211\u559c\u6b22\u559d\u62ff\u94c1"}'),
    h2("9.2 ResponseEnvelope \u5173\u952e\u5b57\u6bb5"),
    table(
      ["\u5b57\u6bb5", "\u542b\u4e49", "\u524d\u7aef\u7528\u9014"],
      [
        ["content", "\u4e3b\u56de\u7b54 Markdown", "\u6c14\u6ce1\u6b63\u6587"],
        ["citations[]", "\u6587\u6863\u5f15\u7528", "\u6765\u6e90\u5361"],
        ["memory_events[]", "\u672c\u8f6e\u5199\u5165\u7684\u8bb0\u5fc6", "\u5e95\u90e8\u63d0\u793a"],
        ["secretary_events[]", "\u8865\u4e01/\u540c\u6b65\u8349\u7a3f", "\u786e\u8ba4\u6309\u94ae"],
        ["tips[]", "\u542f\u53d1\u5f0f\u63d0\u793a", "\u9ec4\u8272\u63d0\u793a\u6761"],
        ["requires_confirmation", "\u662f\u5426\u8981\u4eba\u786e\u8ba4", "\u4e0e\u8865\u4e01\u5361\u540c\u6b65"],
        ["audit_id", "\u672c\u8f6e\u5ba1\u8ba1\u53f7", "\u8c03\u8bd5"],
      ],
      [28, 28, 44]
    ),

    h1("10. 错误码与前端处理约定"),
    table(
      ["HTTP", "code", "\u524d\u7aef\u505a\u4ec0\u4e48"],
      [
        ["200", "-", "\u66f4\u65b0 UI"],
        ["400", "-", "alert / authError \u6587\u6848"],
        ["401", "UNAUTHORIZED", "clearSession \u56de\u767b\u5f55"],
        ["403", "FORBIDDEN", "\u8bb0\u5fc6\u9875\u7ea2\u5b57\uff1b\u7ba1\u7406\u63a5\u53e3\u4e0d\u5c55\u793a"],
        ["404 HTML", "-", "\u63d0\u793a\u91cd\u542f\u540e\u7aef\uff0c\u52ff JSON.parse \u62a5\u9519"],
        ["409", "-", "\u8865\u4e01/\u540c\u6b65\u72b6\u6001\u51b2\u7a81 alert"],
        ["500", "-", "\u6c14\u6ce1\u7ea2\u5b57\u5931\u8d25"],
      ],
      [18, 22, 60]
    ),

    h1("11. cURL 速查（与按钮一一对应）"),
    codeBlock("curl -X POST http://127.0.0.1:8091/v1/auth/login -H \"Content-Type: application/json\" -d \"{\\\"username\\\":\\\"admin\\\",\\\"password\\\":\\\"admin123\\\"}\""),
    codeBlock("curl http://127.0.0.1:8091/v1/auth/me -H \"Authorization: Bearer tok_xxx\""),
    codeBlock("curl -X POST http://127.0.0.1:8091/v1/interactions -H \"Authorization: Bearer tok_xxx\" -H \"Content-Type: application/json\" -d \"{\\\"message\\\":\\\"\u521b\u5efa\u4e00\u4e2a\u4efb\u52a1\uff1a\u5199\u6587\u6863\\\",\\\"channel\\\":\\\"web\\\"}\""),
    codeBlock("curl http://127.0.0.1:8091/v1/admin/users -H \"Authorization: Bearer tok_admin\""),
    p("\u66f4\u5b8c\u6574\u7684\u540e\u7aef\u5b57\u6bb5\u8bf4\u660e\u4ecd\u53ef\u53c2\u8003\u9879\u76ee\u6839\u76ee\u5f55 API.md\u3002\u672c\u6587\u6863\u4ee5\u201c\u9875\u9762\u4f1a\u8c03\u4ec0\u4e48\u201d\u4e3a\u51c6\u3002"),

    h1("12. 验收清单"),
    bullet("\u672a\u767b\u5f55\u6253\u4e0d\u5f00\u63a7\u5236\u53f0\u4e3b\u533a\u57df\u3002"),
    bullet("alice \u770b\u4e0d\u5230\u5168\u7528\u6237\u753b\u50cf\u9762\u677f\uff1badmin \u770b\u5f97\u5230\u5e76\u80fd\u5207\u6362\u3002"),
    bullet("\u5bf9\u8bdd\u5199\u5165\u7684\u8bb0\u5fc6\u53ea\u51fa\u73b0\u5728\u5f53\u524d\u767b\u5f55\u7528\u6237\u533a\u95f4\u3002"),
    bullet("\u4efb\u52a1\u53e5\u5b50\u53ea\u51fa\u73b0\u8349\u7a3f\u8865\u4e01\uff0c\u786e\u8ba4\u540e\u770b\u677f\u624d\u591a\u4e00\u6761\u3002"),
    bullet("\u4e0a\u4f20\u6587\u6863\u540e\u641c\u7d22\u80fd\u51fa snippet\u3002"),
    bullet("\u9000\u51fa\u540e /v1/auth/me \u5fc5\u987b 401\u3002"),
  ];
}

async function writeDoc(filename, title, subtitle, englishLabel, meta, headerTitle, bodyChildren) {
  const doc = new Document({
    styles: styles(),
    numbering: numbering(),
    sections: [
      coverSection(title, subtitle, englishLabel, meta),
      tocSection(),
      bodySection(bodyChildren, headerTitle),
    ],
  });
  const buf = await Packer.toBuffer(doc);
  const out = path.join(__dirname, filename);
  fs.writeFileSync(out, buf);
  console.log("wrote", out, buf.length);
}

async function main() {
  await writeDoc(
    "MyAgentUnified-\u9879\u76ee\u5b8c\u5168\u89e3\u8bfb.docx",
    "MyAgent Unified \u9879\u76ee\u5b8c\u5168\u89e3\u8bfb",
    "\u7ed9\u5c0f\u767d\u7684\u67b6\u6784\u3001\u6280\u672f\u6808\u3001\u80fd\u529b\u8fb9\u754c\u4e0e\u4f7f\u7528\u8bf4\u660e",
    "PRODUCT TECHNICAL BRIEF",
    ["\u6587\u6863\u7c7b\u578b\uff1a\u6280\u672f\u89e3\u8bfb / \u4ea7\u54c1\u8bf4\u660e", "\u9002\u7528\u8bfb\u8005\uff1a\u65b0\u624b\u3001\u4ea7\u54c1\u3001\u4e8c\u6b21\u5f00\u53d1", "\u7248\u672c\uff1a2026-08-20  \u5f53\u524d\u4ee3\u7801\u5e93"],
    "\u9879\u76ee\u5b8c\u5168\u89e3\u8bfb",
    overviewBody()
  );
  await writeDoc(
    "MyAgentUnified-\u524d\u7aef\u63a7\u5236\u53f0\u63a5\u53e3\u6587\u6863.docx",
    "\u524d\u7aef\u63a7\u5236\u53f0\u63a5\u53e3\u6587\u6863",
    "\u754c\u9762\u64cd\u4f5c\u4e0e HTTP API \u4e00\u4e00\u6620\u5c04",
    "UI API SPECIFICATION",
    ["\u8986\u76d6\u9875\u9762\uff1astatic/index.html", "\u57fa\u5730\u5740\uff1ahttp://127.0.0.1:8091", "\u9274\u6743\uff1aBearer Token"],
    "\u524d\u7aef\u63a7\u5236\u53f0\u63a5\u53e3",
    apiDocBody()
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
