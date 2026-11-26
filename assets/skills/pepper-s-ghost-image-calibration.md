---
name: Pepper's Ghost Image Calibration
description: Protocol for configuring optical reflectors and software predistortion to correct image distortion in Pepper's Ghost holographic displays.
updated: 1795057302
sources: https://www.veeb.ch/projects/the-valley-beneath-the-pepper-dome, https://github.com/Cakem1x/peppers_ghost, https://bardofm.substack.com/p/peppers-ghost-hologram, https://pjord.itch.io/peppers-ghost-simulator, https://codingeveryday.com/peppers-ghost-illusion/
---

# Key Concepts and Definitions
*   **Pepper's Ghost Illusion:** A 19th-century optical technique where a transparent surface (acrylic, plastic, glass) reflects an image from a hidden screen toward the viewer's eye, creating the appearance of a floating object in mid-air.
*   **Reflector Distortion:** Using angled surfaces or cones to reflect images introduces geometric distortion. Flat reflectors require angle calibration; conical reflectors require software predistortion.
*   **Virtual Image Position:** The perceived location of the "ghost" is computed by recursively reflecting the source across mirror planes using vector reflection law: $P' = P - 2(P \cdot \hat{n})\hat{n}$.

# How It Works
1.  **Optical Path:** A screen sits face-up (hidden from direct view) under a dome or base. A transparent reflector is set at an angle inside the structure.
2.  **Reflection:** The reflector bounces the screen's image upward. Because the material is transparent, the viewer sees through it to the background while simultaneously seeing the reflection, interpreting it as a floating object.
3.  **Calibration Necessity:** If the reflector angle or shape (e.g., cone) is not accounted for, the image appears skewed or stretched. Calibration aligns the rendered pixels with the physical optical path.

# Hardware Components and Setup
*   **Display Source:** Any bright, high-contrast screen (Raspberry Pi DSI LCD, TV, iPad, Projector).
    *   *Note:* Ribbon cables on some screens may not carry enough power; feed from GPIO header or USB-C port.
*   **Reflector Material:** Clear acrylic sheet, transparent plastic cone, or acetate.
    *   *Safety:* Use flexible plastic rather than glass; tape sharp edges.
*   **Structure:** Glass dome, 3D printed base, or dark box to hide electronics and control ambient light.

# Calibration Protocols

## 1. Flat Reflector Angle Calibration
For flat acrylic sheets (e.g., inside a dome), the angle determines distortion levels.
*   **Eye Level Setup
