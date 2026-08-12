# Houdini COPs → Blender Compositor — concept map

**Grounded both sides.** Houdini **22.0.368** — Copernicus category **`Cop`** (383 types) +
legacy **`Cop2`** (156). Blender **5.2** compositor (168 nodes, in `blender_compositor_schema.json`).
Verify any Blender id with the compositor schema; verify any Houdini name in `houdini_schema.json`
under `categories.Cop`.

## Why this exists in a synthetic-data pipeline
Two jobs: (1) turn **render passes into ground-truth outputs** — segmentation masks, depth,
normals, cryptomatte — and (2) apply **image-space domain randomization** (grain, exposure,
blur, lens effects) to the RGB while leaving label passes pristine. The attribute bridge feeds
this: IDs you `Store Named Attribute` in GN surface as **Object/Material Index / Cryptomatte
passes**, which the compositor turns into masks.

## Reality check (read before mapping)
**Copernicus is a Nuke/Fusion-class GPU image graph; Blender's compositor is much smaller and
coarser.** Copernicus (383 nodes) includes procedural-noise libraries, an SDF toolset,
heightfield ops, FFT, OCIO, and **learned/neural nodes** (SAM2 masks, MoGe-2 depth, ML CV
inference) that Blender simply does not have. Map the overlap; **stay in Copernicus for the
neural/SDF/noise-heavy work** and use Blender's compositor for pass extraction + light grading.

## Blender 5.x compositor model (important)
In 5.x the compositor is a **node-group datablock** (there is no `scene.node_tree`; the classic
single **Composite** output node isn't used inside a group). Wire the graph like this:
- **Inputs:** `Render Layers` (`CompositorNodeRLayers`) — one per view layer, exposing enabled
  passes — and `Image` (`CompositorNodeImage`).
- **Outputs:** `File Output` (`CompositorNodeOutputFile`) with multiple slots → write RGB +
  each label pass (use **multilayer EXR** to keep them in one file). This is your dataset writer.

---

## Crosswalk — Copernicus `Cop` → Blender compositor id

**Blur / DOF**
| Copernicus | Blender |
|---|---|
| `blur` (Blur) | `CompositorNodeBlur` |
| `streakblur` | `CompositorNodeDBlur` (Directional Blur) |
| (bokeh DOF) | `CompositorNodeBokehBlur` + `CompositorNodeBokehImage`; motion → `CompositorNodeVecBlur` |
| (edge-aware) | `CompositorNodeBilateralblur` |

**Transform / distortion**
| Copernicus | Blender |
|---|---|
| `spacetransform`, `uvxform`, `copyxform` | `CompositorNodeTransform` / `Translate` / `Rotate` / `Scale` / `CornerPin` |
| `lensdistort` | `CompositorNodeLensdist` |
| `distort`, `heatdistort` | `CompositorNodeDisplace` (drive by a vector/height layer) |
| `crop` | `CompositorNodeCrop` |
| `flip` | `CompositorNodeFlip` |
| `fft` | — (no equivalent) |

**Color / tone**
| Copernicus | Blender |
|---|---|
| `colorcorrect` | `CompositorNodeColorCorrection`, `CompositorNodeColorBalance` |
| `curves` (via colorcorrect) | `CompositorNodeCurveRGB` |
| `tonemap` | `CompositorNodeTonemap` |
| `gamma` | **not** `Gamma` (dead in 5.2) → `CompositorNodeExposure` / Curves |
| `remap` | `ShaderNodeMapRange`, `CompositorNodeLevels`, `CompositorNodePosterize` |
| `mono` (luminance) | `CompositorNodeRGBToBW` |
| `ramp` | `ShaderNodeValToRGB` (Color Ramp works in compositor) |
| `ociotransform` | — (Blender color mgmt is scene-level, not a node) |

**Merge / composite**
| Copernicus | Blender |
|---|---|
| `average` (Layer Merge), `over` | `CompositorNodeAlphaOver`, `ShaderNodeMix` |
| `zcomp` (Z Composite) | `CompositorNodeZcombine` *(present in 5.2)* |
| `compare`, `compareblend` | math on layers (`Math`/`Map Range`) + `CompositorNodeSwitch` |
| `switch`, `switchbytype` | `CompositorNodeSwitch` |
| `constant` | `CompositorNodeImage`(blank), value nodes |

**Channels**
| Copernicus | Blender |
|---|---|
| `channelsplit` / `channeljoin` | `CompositorNodeSeparateColor` / `CombineColor` |
| `channelextract` / `channelswap` | `Separate/Combine Color`, `CompositorNodeSetAlpha` |

**Filters / edges**
| Copernicus | Blender |
|---|---|
| `sharpen` | `CompositorNodeFilter` (Sharpen preset) |
| `edgedetect`, `edgedetectcontour` | `CompositorNodeFilter` (Sobel/Laplace); stylized → `CompositorNodeKuwahara` |
| `edgedetectdepth`, `edgedetectnormal` | `Filter` fed by the Z / Normal pass |
| (bloom/streaks) | `CompositorNodeGlare` |

**Ground-truth: masks, IDs, passes (the synthetic-data payoff)**
| Copernicus | Blender |
|---|---|
| `cryptomatte`, `cryptomattedecode` | `CompositorNodeCryptomatteV2` |
| `idtomask` | `CompositorNodeIDMask` (fed by Object/Material Index pass) |
| `idtomono`, `idtorgb`, `monotoid` | `ID Mask` + `Separate/Combine Color`; visualize with `Color Ramp` |
| `segmentbyvalue`, `segmentbyconnectivity` | no native segmentation — derive from ID/Cryptomatte passes |
| `convertdepth` | Z pass → `CompositorNodeNormalize` (→0..1 depth map) |
| `denoiseai` | `CompositorNodeDenoise` (OIDN) |
| `denoisetvd` | — |
| `maskcombine` | `Math`/`Mix` on masks; shapes → `Box/Ellipse/DoubleEdge Mask`, `MaskToSDF` |

**Copernicus-only — no Blender compositor equivalent (stay in Houdini)**
`neural_layertomask_sam2` (SAM2 segmentation), `neural_layertodepth_moge2` (monocular depth),
`ml_computervisioninference`, the **procedural noise** family (`cellularnoise`, `curlnoise`,
`crystalnoise`, …), the **SDF** toolset (`monotosdf`, `idtosdf`), **heightfield** ops, `fft`,
`ociotransform`, `livevideo`.

---

## Recommended synthetic-data compositor graph (Blender 5.2)

```
Render Layers (enable passes: Combined, Depth/Z, Normal, Cryptomatte,
               Object Index and/or Material Index)
   ├─ Combined ─▶ [domain randomization: Exposure ▸ Color Balance ▸ Blur ▸ Lens Distortion ▸ Glare]
   │                 ─▶ File Output slot "rgb"
   ├─ Z ───────▶ Normalize ─▶ File Output slot "depth"
   ├─ Normal ──▶ File Output slot "normal"
   ├─ IndexOB ─▶ ID Mask(index=k) ─▶ File Output slot "mask_k"     # per-class masks
   └─ Cryptomatte V2 ─▶ (matte extraction) ─▶ File Output slot "instance_id"
```
Rules of thumb:
- **Randomize the RGB path only.** Never blur/grade the label passes — masks/depth must stay
  pixel-exact ground truth.
- **Object Index vs Material Index vs Cryptomatte:** Object Index = per-object int (set via GN
  `Set Material Index` or object pass); Cryptomatte = robust per-instance/asset mattes even with
  overlap/motion blur → prefer it for instance segmentation.
- **Write multilayer EXR** from one `File Output` so RGB + all labels stay aligned per frame.
- The class/instance ids themselves originate in **Geometry Nodes** via the attribute bridge —
  see `attribute_bridge.md` §"Segmentation / class ID".

## Legacy note
`Cop2` (156 nodes) is the pre-Copernicus COP2 network (context `img`). Same crosswalk mostly
applies at the concept level, but on H22 you're almost certainly authoring in Copernicus (`Cop`).
