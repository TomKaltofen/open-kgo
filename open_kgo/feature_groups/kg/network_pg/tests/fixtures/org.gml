graph [
  directed 1
  node [ id 0 label "alice" name "Alice" team "platform" ]
  node [ id 1 label "bob" name "Bob" team "platform" ]
  node [ id 2 label "carol" name "Carol" team "data" ]
  edge [ source 0 target 1 label "MANAGES" ]
  edge [ source 1 target 2 label "MANAGES" ]
]
