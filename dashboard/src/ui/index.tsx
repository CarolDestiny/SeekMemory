import type { ComponentProps, ReactNode } from "react"

import { Badge as ShadcnBadge } from "./shadcn/badge"
import { Button as ShadcnButton } from "./shadcn/button"
import { Input as ShadcnInput } from "./shadcn/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "./shadcn/sheet"
import { Skeleton as ShadcnSkeleton } from "./shadcn/skeleton"
import {
  Tabs as ShadcnTabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "./shadcn/tabs"

// Public contracts use React/DOM types, never component-vendor prop types.
export interface ButtonProps extends ComponentProps<"button"> {
  variant?:
    "default" | "outline" | "secondary" | "ghost" | "destructive" | "link"
  size?:
    "default" | "xs" | "sm" | "lg" | "icon" | "icon-xs" | "icon-sm" | "icon-lg"
}

export function Button(props: ButtonProps) {
  return <ShadcnButton {...props} />
}

export interface BadgeProps extends ComponentProps<"span"> {
  variant?:
    "default" | "secondary" | "destructive" | "outline" | "ghost" | "link"
}

export function Badge(props: BadgeProps) {
  return <ShadcnBadge {...props} />
}

export function Input(props: ComponentProps<"input">) {
  return <ShadcnInput {...props} />
}

export function Skeleton(props: ComponentProps<"div">) {
  return <ShadcnSkeleton {...props} />
}

export interface SelectOption<T extends string> {
  readonly value: T
  readonly label: string
}

interface SelectProps<T extends string> {
  id?: string
  label: string
  value: T
  options: readonly SelectOption<T>[]
  onValueChange: (value: T) => void
  className?: string
}

export function Select<T extends string>({
  id,
  label,
  value,
  options,
  onValueChange,
  className,
}: SelectProps<T>) {
  return (
    <select
      id={id}
      aria-label={label}
      value={value}
      className={["filter-select", className].filter(Boolean).join(" ")}
      onChange={(event) => {
        const option = options.find((item) => item.value === event.target.value)
        if (option) onValueChange(option.value)
      }}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

interface DetailDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  children: ReactNode
}

export function DetailDrawer({
  open,
  onOpenChange,
  title,
  description,
  children,
}: DetailDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-lg">
        <SheetHeader className="sr-only">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        <div className="pt-8">{children}</div>
      </SheetContent>
    </Sheet>
  )
}

interface TabItem<T extends string> {
  readonly value: T
  readonly label: ReactNode
  readonly content: ReactNode
}

interface TabsProps<T extends string> {
  items: readonly TabItem<T>[]
  defaultValue: NoInfer<T>
}

export function Tabs<T extends string>({ items, defaultValue }: TabsProps<T>) {
  return (
    <ShadcnTabs defaultValue={defaultValue} className="gap-0">
      <TabsList
        variant="line"
        className="mx-6 mb-1 w-[calc(100%-3rem)] justify-start border-b"
      >
        {items.map((item) => (
          <TabsTrigger key={item.value} value={item.value}>
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {items.map((item) => (
        <TabsContent key={item.value} value={item.value}>
          {item.content}
        </TabsContent>
      ))}
    </ShadcnTabs>
  )
}
