/**
 * PostprocessingEffects — Shared bloom/glow effects for React Three Fiber scenes.
 *
 * Drop into any <Canvas> to get cinematic bloom on emissive materials,
 * chromatic aberration, and vignette. Designed for the Princeps aesthetic.
 *
 * Usage:
 *   <Canvas>
 *     <PostprocessingEffects bloom={1.2} />
 *     <YourScene />
 *   </Canvas>
 */
import React from "react";
import { EffectComposer, Bloom, ChromaticAberration, Vignette } from "@react-three/postprocessing";
import { BlendFunction } from "postprocessing";

export default function PostprocessingEffects({
  bloom = 1.0,
  bloomThreshold = 0.4,
  bloomSmoothing = 0.6,
  chromaticAberration = 0.002,
  vignette = 0.45,
  enabled = true,
}) {
  if (!enabled) return null;

  return (
    <EffectComposer multisampling={4}>
      <Bloom
        intensity={bloom}
        luminanceThreshold={bloomThreshold}
        luminanceSmoothing={bloomSmoothing}
        mipmapBlur
      />
      {chromaticAberration > 0 && (
        <ChromaticAberration
          blendFunction={BlendFunction.NORMAL}
          offset={[chromaticAberration, chromaticAberration]}
        />
      )}
      {vignette > 0 && (
        <Vignette
          eskil={false}
          offset={0.1}
          darkness={vignette}
        />
      )}
    </EffectComposer>
  );
}
