// ocr.swift — macOS 內建 Vision OCR（圖片與 PDF）
// 用 Apple 的 Vision framework，中文辨識品質好，且不需任何第三方套件。
// 編譯：swiftc -O -o ocr ocr.swift -framework Vision -framework PDFKit -framework AppKit
// 用法：./ocr <檔案> [--lang zh-Hant,en-US] [--fast]

import Foundation
import Vision
import PDFKit
import AppKit

func recognize(_ cg: CGImage, langs: [String], fast: Bool) -> String {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = fast ? .fast : .accurate
    req.recognitionLanguages = langs
    req.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([req]) } catch { return "" }
    guard let obs = req.results else { return "" }
    return obs.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func imageOCR(_ path: String, _ langs: [String], _ fast: Bool) -> String {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("[讀不到影像] \(path)\n".data(using: .utf8)!)
        return ""
    }
    return recognize(cg, langs: langs, fast: fast)
}

func pdfOCR(_ path: String, _ langs: [String], _ fast: Bool) -> String {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else {
        FileHandle.standardError.write("[開不了 PDF] \(path)\n".data(using: .utf8)!)
        return ""
    }
    var out: [String] = []
    for i in 0..<doc.pageCount {
        guard let page = doc.page(at: i) else { continue }
        // 先看有沒有文字層，有就直接取，省下 OCR 的時間
        if let t = page.string, t.trimmingCharacters(in: .whitespacesAndNewlines).count > 20 {
            out.append("── 第 \(i+1) 頁（文字層）──\n" + t)
            continue
        }
        // 沒有文字層才 OCR：放大 2 倍提高辨識率
        let bounds = page.bounds(for: .mediaBox)
        let scale: CGFloat = 2.0
        let w = Int(bounds.width * scale), h = Int(bounds.height * scale)
        guard w > 0, h > 0,
              let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                                  bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
        ctx.scaleBy(x: scale, y: scale)
        page.draw(with: .mediaBox, to: ctx)
        guard let cg = ctx.makeImage() else { continue }
        let t = recognize(cg, langs: langs, fast: fast)
        if !t.isEmpty { out.append("── 第 \(i+1) 頁（OCR）──\n" + t) }
    }
    return out.joined(separator: "\n\n")
}

let args = CommandLine.arguments
guard args.count > 1 else {
    print("用法：ocr <檔案> [--lang zh-Hant,en-US] [--fast]")
    exit(1)
}
var langs = ["zh-Hant", "en-US"]
if let i = args.firstIndex(of: "--lang"), i + 1 < args.count {
    langs = args[i + 1].split(separator: ",").map(String.init)
}
let fast = args.contains("--fast")
let path = args[1]
let ext = (path as NSString).pathExtension.lowercased()
let text = (ext == "pdf") ? pdfOCR(path, langs, fast) : imageOCR(path, langs, fast)
print(text)
