// Read the text on a street-map picture with Apple's Vision framework (on every Mac, no install).
// Street labels run along the streets, so the picture is read three times - upright, turned left and
// turned right - and every box is given back in the ORIGINAL picture's pixel coordinates.
//   swift ocr.swift picture.png > words.json
import Foundation
import Vision
import CoreImage
import AppKit

let path = CommandLine.arguments[1]
guard let ns = NSImage(contentsOfFile: path), let cg = ns.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("[]"); exit(0) }
let W = Double(cg.width), H = Double(cg.height)
var out: [[String: Any]] = []
for (rot, orient) in [(0, CGImagePropertyOrientation.up), (90, .right), (270, .left)] {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    req.minimumTextHeight = 0.004
    let h = VNImageRequestHandler(cgImage: cg, orientation: orient, options: [:])
    try? h.perform([req])
    for r in (req.results ?? []) {
        guard let c = r.topCandidates(1).first else { continue }
        // box corners, normalised in the (rotated) view Vision saw; map back to the original picture
        guard let q = try? c.boundingBox(for: c.string.startIndex..<c.string.endIndex) else { continue }
        func back(_ p: CGPoint) -> [Double] {
            // Vision's normalised coords are in the oriented image, origin bottom-left
            let x = Double(p.x), y = Double(p.y)
            switch rot {
            case 90:  return [(1 - y) * W, (1 - x) * H]   // .right: displayed = original rotated 90 cw
            case 270: return [y * W, x * H]
            default:  return [x * W, (1 - y) * H]
            }
        }
        out.append(["t": c.string, "c": Double(c.confidence), "rot": rot,
                    "p": [back(q.topLeft), back(q.topRight), back(q.bottomRight), back(q.bottomLeft)]])
    }
}
let data = try! JSONSerialization.data(withJSONObject: out, options: [])
print(String(data: data, encoding: .utf8)!)
